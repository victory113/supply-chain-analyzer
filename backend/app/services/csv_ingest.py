"""CSV ingestion: parse, map columns, derive, validate, normalise.

Real supply-chain exports share no header schema, so columns are matched by
alias rather than exact name, the delimiter is sniffed, and unparseable *cells*
degrade to null instead of failing the whole file.

Two behaviours matter most for real data:

* **Derivation.** Exports almost never carry a ``delay_days`` column. They carry
  a scheduled date and an actual date and expect you to subtract. Without this,
  every shipment in a real dataset looks on-time and the risk score reads zero.
* **Streaming.** Rows are yielded in batches so peak memory tracks the batch
  size, not the file size. A 100 MB upload would otherwise materialise hundreds
  of thousands of ORM objects at once and exhaust a small instance.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from typing import IO

from app.core.config import settings
from app.core.exceptions import PayloadTooLargeError, ValidationError
from app.core.logging import get_logger
from app.models.enums import ShipmentStatus
from app.models.shipment import Shipment
from app.schemas.upload import IngestReport

logger = get_logger(__name__)

# Canonical field -> accepted header aliases. Compared after lowercasing and
# stripping every non-alphanumeric character, so "Unit Cost", "unit_cost" and
# "UNIT-COST" all collapse to the same key.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "shipment_ref": (
        "shipmentid",
        "shipment",
        "shipmentref",
        "id",
        "ref",
        "ordernumber",
        "po",
        "orderid",
        "ordernum",
        "trackingnumber",
        "tracking",
        "asnnumber",
        "poso",
        "ponumber",
        "sonumber",
        "recordid",
        "lineitem",
        "lineitemid",
    ),
    "vendor": (
        "vendor",
        "supplier",
        "suppliername",
        "vendorname",
        "manufacturer",
        "manufacturingsite",
        "shipper",
        "carrier",
        "seller",
        "sellerid",
        "supplierid",
        "vendorid",
        "partner",
    ),
    "product": (
        "product",
        "item",
        "sku",
        "material",
        "description",
        "productname",
        "itemdescription",
        "productcategory",
        "categoryname",
        "molecule",
        "producttype",
        "commodity",
        "productid",
        "itemname",
        "brand",
    ),
    "origin_country": (
        "origincountry",
        "origin",
        "country",
        "sourcecountry",
        "from",
        "manufacturingcountry",
        "countryoforigin",
        "shipfrom",
        "originport",
        "ordercountry",
        "sourceregion",
        "originregion",
    ),
    "destination": (
        "destination",
        "dest",
        "shipto",
        "deliverylocation",
        "to",
        "destinationcountry",
        "customercountry",
        "customerstate",
        "customercity",
        "deliverycountry",
        "consignee",
        "destinationport",
        "region",
    ),
    "quantity": (
        "quantity",
        "qty",
        "units",
        "volume",
        "orderqty",
        "lineitemquantity",
        "orderitemquantity",
        "shippedqty",
        "quantityshipped",
        "pack",
        "orderquantity",
        "unitssold",
    ),
    "unit_cost": (
        "unitcost",
        "cost",
        "price",
        "unitprice",
        "costperunit",
        "pack_price",
        "packprice",
        "lineitemvalue",
        "orderitemproductprice",
        "productprice",
        "sales",
        "value",
        "unitvalue",
        "amount",
    ),
    "lead_time_days": (
        "leadtimedays",
        "leadtime",
        "leadtimeindays",
        "transitdays",
        "daysforshipmentscheduled",
        "scheduleddays",
        "shippingdays",
        "plannedtransitdays",
        "promiseddays",
    ),
    "delay_days": (
        "delaydays",
        "delay",
        "daysdelayed",
        "dayslate",
        "latedays",
        "delayindays",
        "latenessdays",
        "daysbehindschedule",
        "slippagedays",
    ),
    "status": (
        "status",
        "shipmentstatus",
        "state",
        "deliverystatus",
        "orderstatus",
        "shippingstatus",
        "fulfilmentstatus",
        "fulfillmentstatus",
    ),
    "shipped_on": (
        "shippedon",
        "shipdate",
        "shipped",
        "dispatchdate",
        "orderdate",
        "shippingdate",
        "orderdatedateorders",
        "shippingdatedateorders",
        "purchasedate",
        "createdat",
        "orderpurchasetimestamp",
        "pickupdate",
    ),
    # Promised / planned arrival.
    "scheduled_delivery": (
        "scheduleddeliverydate",
        "expecteddeliverydate",
        "promiseddate",
        "estimateddeliverydate",
        "eta",
        "duedate",
        "requireddate",
        "plannedarrival",
        "targetdeliverydate",
        "orderestimateddeliverydate",
        "scheduledarrival",
        "expectedarrival",
    ),
    # Actual arrival.
    "actual_delivery": (
        "deliveredtoclientdate",
        "actualdeliverydate",
        "deliverydate",
        "delivereddate",
        "receiveddate",
        "actualarrival",
        "arrivaldate",
        "ordercustomerdeliverydate",
        "completiondate",
        "closeddate",
        "actualreceiptdate",
        "goodsreceiptdate",
    ),
    "last_updated": (
        "lastupdated",
        "updated",
        "updatedat",
        "asof",
        "reportdate",
        "snapshotdate",
        "extractdate",
        "modifiedat",
    ),
}

# Ordered most-specific first: a bare "%Y-%m-%d" would happily swallow the date
# part of an ISO timestamp and silently discard the time.
DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%m/%d/%Y %H:%M",
    "%d/%m/%Y %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%m-%d-%Y",
    "%d.%m.%Y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%b %d, %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%Y%m%d",
)

# Delimiters worth trying. Semicolon is the default CSV separator in locales
# that use a comma for decimals, so European exports are full of them.
CANDIDATE_DELIMITERS = ",;\t|"

# Values that mean "no data" in exported spreadsheets.
NULL_TOKENS = frozenset(
    {"", "na", "n/a", "#n/a", "null", "none", "nil", "-", "--", "nan", "unknown"}
)


def _normalize_header(header: str) -> str:
    return "".join(ch for ch in header.lower() if ch.isalnum())


def map_columns(headers: list[str]) -> tuple[dict[str, str], list[str]]:
    """Return (canonical_field -> original_header, unmapped_headers)."""
    mapping: dict[str, str] = {}
    used: set[str] = set()

    for field_name, aliases in COLUMN_ALIASES.items():
        for header in headers:
            if header in used:
                continue
            if _normalize_header(header) in aliases:
                mapping[field_name] = header
                used.add(header)
                break

    unmapped = [h for h in headers if h not in used]
    return mapping, unmapped


def _is_null(raw: str | None) -> bool:
    return raw is None or raw.strip().lower() in NULL_TOKENS


def _parse_int(raw: str | None) -> int | None:
    if _is_null(raw):
        return None
    cleaned = raw.strip().replace(",", "").replace("_", "").replace(" ", "")  # type: ignore[union-attr]
    try:
        # float() first so "1200.0" from a spreadsheet export still parses.
        return int(float(cleaned))
    except ValueError:
        return None


def _parse_float(raw: str | None) -> float | None:
    if _is_null(raw):
        return None
    cleaned = raw.strip()  # type: ignore[union-attr]
    for symbol in ("$", "€", "£", "¥", ",", " "):
        cleaned = cleaned.replace(symbol, "")
    # Accounting notation: (1,234.00) means negative.
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    try:
        return float(cleaned)
    except ValueError:
        return None


@lru_cache(maxsize=16_384)
def _strptime_any(cleaned: str) -> date | None:
    """Try each supported format until one sticks.

    Cached because this is the hot loop of a large ingest: matching a format
    means raising and catching a ``ValueError`` for every format ahead of it,
    and a file with two date columns over a year holds only a few hundred
    *distinct* date strings across hundreds of thousands of rows. The cache
    turns 3M strptime attempts into a few hundred.
    """
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _parse_date(raw: str | None) -> date | None:
    if _is_null(raw):
        return None
    return _strptime_any(raw.strip())  # type: ignore[union-attr]


def _clean_str(raw: str | None, *, max_length: int) -> str | None:
    if _is_null(raw):
        return None
    cleaned = raw.strip()  # type: ignore[union-attr]
    return cleaned[:max_length] if cleaned else None


@dataclass
class IngestStats:
    """Counters accumulated while streaming. Owned by the caller."""

    accepted: int = 0
    rejected: int = 0
    derived_delays: int = 0
    detected_columns: dict[str, str] = field(default_factory=dict)
    unmapped_columns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    truncated: bool = False

    def to_report(self) -> IngestReport:
        return IngestReport(
            accepted_rows=self.accepted,
            rejected_rows=self.rejected,
            derived_delays=self.derived_delays,
            detected_columns=self.detected_columns,
            unmapped_columns=self.unmapped_columns,
            warnings=self.warnings,
        )


@dataclass
class IngestResult:
    """Fully-materialised parse. Convenient for tests and small files."""

    shipments: list[Shipment]
    report: IngestReport
    warnings: list[str] = field(default_factory=list)


class CsvIngestService:
    """Turns a CSV byte stream into validated ``Shipment`` rows."""

    def __init__(
        self,
        *,
        max_bytes: int | None = None,
        max_rows: int | None = None,
        batch_size: int | None = None,
    ) -> None:
        self.max_bytes = max_bytes or settings.max_upload_bytes
        self.max_rows = max_rows or settings.max_rows_per_upload
        self.batch_size = batch_size or settings.ingest_batch_size

    # ── Public API ────────────────────────────────────────────────────

    def parse(self, content: bytes, upload_id: uuid.UUID) -> IngestResult:
        """Parse everything into memory. Used by tests and modest files."""
        stats = IngestStats()
        shipments: list[Shipment] = []
        for batch in self.stream_batches(io.BytesIO(content), upload_id, stats):
            shipments.extend(batch)
        return IngestResult(shipments=shipments, report=stats.to_report(), warnings=stats.warnings)

    def stream_batches(
        self, raw: IO[bytes], upload_id: uuid.UUID, stats: IngestStats
    ) -> Iterator[list[Shipment]]:
        """Yield shipments in batches, keeping peak memory bounded.

        ``stats`` is mutated as rows are consumed and is only complete once the
        iterator is exhausted.
        """
        size = self._size_of(raw)
        if size > self.max_bytes:
            raise PayloadTooLargeError(
                f"File is {size / 1_048_576:.1f} MB; the limit is "
                f"{self.max_bytes / 1_048_576:.0f} MB."
            )

        encoding = self._sniff_encoding(raw)
        text_stream = io.TextIOWrapper(raw, encoding=encoding, newline="")
        delimiter = self._sniff_delimiter(text_stream)

        skipped = self._find_header_offset(text_stream, delimiter)
        text_stream.seek(0)
        for _ in range(skipped):
            text_stream.readline()

        reader = csv.DictReader(text_stream, delimiter=delimiter)
        if not reader.fieldnames:
            raise ValidationError("The file has no header row.")

        if skipped:
            stats.warnings.append(
                f"Skipped {skipped} line(s) above the header row."
                if skipped > 1
                else "Skipped 1 line above the header row."
            )

        headers = [h for h in reader.fieldnames if h]
        mapping, unmapped = map_columns(headers)
        stats.detected_columns = mapping
        stats.unmapped_columns = unmapped

        if not mapping:
            raise ValidationError(
                "No recognisable supply-chain columns found. Expected at least one "
                "column describing a vendor, product, date, quantity or status.",
                details={
                    "found_headers": headers[:40],
                    "delimiter_used": delimiter,
                    "recognised_fields": sorted(COLUMN_ALIASES),
                },
            )

        stats.warnings.extend(self._advisory_warnings(mapping))

        batch: list[Shipment] = []
        for index, row in enumerate(reader, start=2):  # row 1 is the header
            if stats.accepted >= self.max_rows:
                stats.truncated = True
                stats.warnings.append(
                    f"File truncated at {self.max_rows:,} rows; the rest was ignored."
                )
                break

            shipment = self._build_shipment(row, mapping, upload_id, stats)
            if shipment is None:
                stats.rejected += 1
                if stats.rejected <= 5:  # cap the noise on a badly-formed file
                    logger.debug("row_rejected", row_number=index)
                continue

            batch.append(shipment)
            stats.accepted += 1
            if len(batch) >= self.batch_size:
                yield batch
                batch = []

        if batch:
            yield batch

        if stats.accepted == 0:
            raise ValidationError(
                "No usable rows found. Every row was blank or had no values in any "
                "recognised column.",
                details={
                    "rejected_rows": stats.rejected,
                    "detected_columns": mapping,
                    "delimiter_used": delimiter,
                },
            )

        # Derivation is *not* appended to `warnings`: it travels as the
        # structured `derived_delays` count instead, so callers can phrase it
        # themselves without the UI printing the same fact twice.
        if stats.derived_delays:
            logger.info("delays_derived", count=stats.derived_delays)

    # ── Format detection ──────────────────────────────────────────────

    @staticmethod
    def _size_of(raw: IO[bytes]) -> int:
        current = raw.tell()
        raw.seek(0, io.SEEK_END)
        size = raw.tell()
        raw.seek(current)
        return size

    @staticmethod
    def _sniff_encoding(raw: IO[bytes]) -> str:
        """Pick an encoding from a probe of the first chunk.

        Excel on Windows emits UTF-8-with-BOM or cp1252 constantly; rejecting
        those would fail the single most common real upload. latin-1 is last
        because it decodes any byte sequence and so always "succeeds".
        """
        probe = raw.read(64 * 1024)
        raw.seek(0)
        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                probe.decode(encoding)
            except UnicodeDecodeError:
                continue
            return encoding
        raise ValidationError("File is not valid text in any supported encoding.")

    @staticmethod
    def _sniff_delimiter(text_stream: io.TextIOWrapper) -> str:
        """Detect the separator, defaulting to a comma.

        csv.Sniffer is confidently wrong on files with quoted free text, so its
        answer is only accepted when it names one of the candidates.
        """
        sample = text_stream.read(64 * 1024)
        text_stream.seek(0)
        if not sample:
            return ","
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=CANDIDATE_DELIMITERS)
        except csv.Error:
            # Fall back to whichever candidate appears most in the header line.
            header = sample.splitlines()[0] if sample.splitlines() else ""
            counts = {d: header.count(d) for d in CANDIDATE_DELIMITERS}
            best = max(counts, key=lambda d: counts[d])
            return best if counts[best] else ","
        return dialect.delimiter if dialect.delimiter in CANDIDATE_DELIMITERS else ","

    @staticmethod
    def _find_header_offset(
        text_stream: io.TextIOWrapper, delimiter: str, max_scan: int = 15
    ) -> int:
        """Number of lines to discard before the real header row.

        Spreadsheet exports routinely open with a report title, a blank line
        and a "Generated on …" stamp before the header. Line 0 is the answer
        for nearly every file, so this costs one extra pass over a handful of
        lines — and rescues the files that would otherwise be rejected outright
        for having no recognisable columns.
        """
        text_stream.seek(0)
        reader = csv.reader(text_stream, delimiter=delimiter)
        for offset, row in enumerate(reader):
            if offset >= max_scan:
                break
            mapping, _ = map_columns([cell for cell in row if cell])
            if mapping:
                return offset
        # Nothing matched anywhere; leave it at the top so the error the caller
        # raises names the file's actual first row.
        return 0

    @staticmethod
    def _advisory_warnings(mapping: dict[str, str]) -> list[str]:
        warnings: list[str] = []
        if "vendor" not in mapping:
            warnings.append("No vendor column detected — vendor health ranking is unavailable.")
        if not {"delay_days", "scheduled_delivery"} & mapping.keys():
            warnings.append(
                "No delay column, and no scheduled/actual date pair to derive one "
                "from — delay metrics will read as zero."
            )
        if not {"shipped_on", "actual_delivery", "scheduled_delivery", "last_updated"} & (
            mapping.keys()
        ):
            warnings.append("No date column detected — the monthly trend chart cannot be plotted.")
        return warnings

    # ── Row construction ──────────────────────────────────────────────

    @staticmethod
    def _build_shipment(
        row: dict[str, str | None],
        mapping: dict[str, str],
        upload_id: uuid.UUID,
        stats: IngestStats,
    ) -> Shipment | None:
        def value(field_name: str) -> str | None:
            header = mapping.get(field_name)
            return row.get(header) if header else None

        # A row is usable if *any* recognised column holds a value. The older
        # rule required a vendor, ref or product specifically, which rejected
        # entire real datasets whose identity column we hadn't aliased yet.
        if all(_is_null(value(field_name)) for field_name in mapping):
            return None

        scheduled = _parse_date(value("scheduled_delivery"))
        actual = _parse_date(value("actual_delivery"))
        shipped = _parse_date(value("shipped_on"))

        delay = _parse_int(value("delay_days"))
        if delay is None and scheduled and actual:
            # The derivation that makes real exports usable: they carry two
            # dates and expect the consumer to subtract.
            delay = (actual - scheduled).days
            stats.derived_delays += 1

        lead_time = _parse_int(value("lead_time_days"))
        if lead_time is None and shipped and actual:
            lead_time = max((actual - shipped).days, 0)

        status = ShipmentStatus.parse(value("status"))
        if status is ShipmentStatus.UNKNOWN and delay is not None:
            # Infer from the delay so success-rate maths isn't silently wrong.
            status = ShipmentStatus.DELAYED if delay > 0 else ShipmentStatus.ON_TIME

        # One date field drives the trend chart. Prefer when it shipped, then
        # when it arrived, then when it was due — any of them places the
        # shipment in the right month.
        occurred_on = shipped or actual or scheduled

        return Shipment(
            upload_id=upload_id,
            shipment_ref=_clean_str(value("shipment_ref"), max_length=128),
            vendor=_clean_str(value("vendor"), max_length=255),
            product=_clean_str(value("product"), max_length=255),
            origin_country=_clean_str(value("origin_country"), max_length=128),
            destination=_clean_str(value("destination"), max_length=255),
            quantity=_parse_int(value("quantity")),
            unit_cost=_parse_float(value("unit_cost")),
            lead_time_days=lead_time,
            delay_days=max(delay or 0, 0),  # negative "delays" are early arrivals
            status=status,
            shipped_on=occurred_on,
            last_updated=_parse_date(value("last_updated")) or actual,
        )
