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
from difflib import SequenceMatcher
from functools import lru_cache
from typing import IO

from app.core.config import settings
from app.core.exceptions import PayloadTooLargeError, ValidationError
from app.core.logging import get_logger
from app.models.enums import ShipmentStatus, TransportMode
from app.models.shipment import Shipment
from app.schemas.upload import IngestReport

logger = get_logger(__name__)

# Canonical field -> accepted header aliases. Compared after lowercasing and
# stripping every non-alphanumeric character, so "Unit Cost", "unit_cost" and
# "UNIT-COST" all collapse to the same key.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    # NOTE ON ORDERING: a header is claimed by the first field that matches, so
    # broad fields must not list aliases that a more specific field owns. That
    # is why "carrier" is absent from `vendor` and "sku"/"brand"/"category" are
    # absent from `product` — those columns now have fields of their own, and
    # leaving them here would quietly starve the new analytics.
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
        "asnnumber",
        "poso",
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
        "seller",
        "sellerid",
        "supplierid",
        "vendorid",
        "partner",
    ),
    "product": (
        "product",
        "item",
        "material",
        "description",
        "productname",
        "itemdescription",
        "molecule",
        "commodity",
        "productid",
        "itemname",
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
        "customerstate",
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
        "promiseddeliverydate",
        "planneddeliverydate",
        "committeddeliverydate",
        "agreeddeliverydate",
        "estimatedarrivaldate",
        "expectedarrivaldate",
        "targetdate",
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
    # ── Identifiers ───────────────────────────────────────────────────
    "order_ref": (
        "orderref",
        "salesorder",
        "salesordernumber",
        "sonumber",
        "purchaseorder",
        "purchaseordernumber",
        "customerordernumber",
        "orderreference",
    ),
    "tracking_number": (
        "trackingnumber",
        "trackingid",
        "trackingref",
        "waybill",
        "waybillnumber",
        "airwaybill",
        "awb",
        "billoflading",
        "bol",
        "pronumber",
        "consignmentnumber",
    ),
    "customer_ref": (
        "customerid",
        "customerref",
        "customernumber",
        "accountid",
        "accountnumber",
        "clientid",
    ),
    # ── Parties ───────────────────────────────────────────────────────
    "carrier": (
        "carrier",
        "carriername",
        "logisticsprovider",
        "freightforwarder",
        "forwarder",
        "transporter",
        "haulier",
        "trucker",
        "shippingline",
        "courier",
        "carriercode",
        "3pl",
    ),
    "customer": (
        "customer",
        "customername",
        "client",
        "clientname",
        "consigneename",
        "buyer",
        "shiptoname",
    ),
    "service_level": (
        "servicelevel",
        "service",
        "servicetype",
        "shippingmethod",
        "shipmethod",
        "deliveryservice",
        "shippingservice",
        "servicecode",
    ),
    # ── Product ───────────────────────────────────────────────────────
    "sku": ("sku", "skucode", "skuid", "itemcode", "materialnumber", "partnumber", "itemnumber"),
    "category": (
        "category",
        "productcategory",
        "categoryname",
        "itemcategory",
        "productline",
        "commoditygroup",
        "producttype",
        "segment",
    ),
    "brand": ("brand", "brandname", "make", "label"),
    "quantity_delivered": (
        "quantitydelivered",
        "deliveredquantity",
        "qtydelivered",
        "receivedquantity",
        "quantityreceived",
        "qtyreceived",
        "quantityfulfilled",
        "shippedquantity",
    ),
    "currency": ("currency", "currencycode", "curr", "ccy"),
    "weight_kg": (
        "weight",
        "weightkg",
        "grossweight",
        "netweight",
        "totalweight",
        "shipmentweight",
        "chargeableweight",
        "weightkilograms",
    ),
    "hazardous": (
        "hazardous",
        "hazmat",
        "hazardousmaterial",
        "dangerousgoods",
        "isdangerous",
        "dg",
    ),
    "temperature_controlled": (
        "temperaturecontrolled",
        "refrigerated",
        "reefer",
        "coldchain",
        "tempcontrolled",
        "chilled",
    ),
    # ── Geography ─────────────────────────────────────────────────────
    "origin_city": ("origincity", "shipfromcity", "sourcecity", "pickupcity", "departurecity"),
    "destination_country": (
        "destinationcountry",
        "deliverycountry",
        "shiptocountry",
        "consigneecountry",
        "receivingcountry",
    ),
    "destination_city": (
        "destinationcity",
        "deliverycity",
        "shiptocity",
        "consigneecity",
        "arrivalcity",
    ),
    "warehouse": (
        "warehouse",
        "warehouseid",
        "warehousename",
        "distributioncenter",
        "distributioncentre",
        "dc",
        "facility",
        "fulfilmentcenter",
        "fulfillmentcenter",
        "site",
    ),
    # ── Transport ─────────────────────────────────────────────────────
    "transport_mode": (
        "transportmode",
        "mode",
        "modeoftransport",
        "shipmentmode",
        "shippingmode",
        "transportationmode",
        "shipmenttype",
        "freightmode",
        "modeofshipment",
    ),
    "container_ref": ("container", "containernumber", "containerid", "containerref", "equipmentid"),
    "vehicle_ref": (
        "vehicleid",
        "vehicle",
        "trucknumber",
        "truckid",
        "flightnumber",
        "vesselname",
        "vessel",
        "voyage",
        "trailernumber",
    ),
    "route_ref": ("routeid", "route", "routecode", "lane", "lanecode", "laneid"),
    "package_count": (
        "packages",
        "packagecount",
        "numberofpackages",
        "cartons",
        "cartoncount",
        "pallets",
        "palletcount",
        "pieces",
        "piececount",
        "numpackages",
    ),
    "distance_km": (
        "distance",
        "distancekm",
        "distancekilometers",
        "distancetravelled",
        "distancemiles",
        "shippingdistance",
        "routedistance",
    ),
    # ── Timing ────────────────────────────────────────────────────────
    "transit_days": (
        "transittime",
        "transitdaysactual",
        "actualtransitdays",
        "daysintransit",
        "daysforshippingreal",
        "actualshippingdays",
        "realshippingdays",
    ),
    "priority": ("priority", "orderpriority", "shipmentpriority", "urgency", "prioritylevel"),
    # ── Money ─────────────────────────────────────────────────────────
    "freight_cost": (
        "freightcost",
        "freight",
        "shippingcost",
        "freightcharge",
        "transportcost",
        "carriercost",
        "shippingcharges",
        "freightamount",
        "haulagecost",
    ),
    "insurance_cost": ("insurancecost", "insurance", "insuranceamount", "insurancecharge"),
    "customs_duty": (
        "customsduty",
        "duty",
        "dutyamount",
        "tariff",
        "tariffamount",
        "importduty",
        "customscharges",
    ),
    "total_cost": (
        "totalcost",
        "totalshipmentcost",
        "landedcost",
        "totallandedcost",
        "invoiceamount",
        "totalamount",
        "totalspend",
        "grandtotal",
    ),
    # ── Quality ───────────────────────────────────────────────────────
    "damaged": ("damaged", "damage", "isdamaged", "damagedflag", "damagereported"),
    "returned": ("returned", "isreturned", "returnflag", "rma", "returnrequested"),
    # ── Customs ───────────────────────────────────────────────────────
    "incoterms": ("incoterms", "incoterm", "termsofdelivery", "deliveryterms", "tradeterms"),
    "hs_code": ("hscode", "harmonizedcode", "harmonisedcode", "tariffcode", "commoditycode"),
    # ── Sustainability ────────────────────────────────────────────────
    "co2_kg": (
        "co2",
        "co2kg",
        "co2emissions",
        "carbonemissions",
        "emissions",
        "carbonfootprint",
        "ghgemissions",
        "co2e",
    ),
}

# Values that read as "yes" in a boolean-ish column. Anything else non-null is
# treated as false; a blank stays None so "we don't know" survives.
TRUE_TOKENS = frozenset({"true", "yes", "y", "1", "t", "damaged", "returned"})
FALSE_TOKENS = frozenset({"false", "no", "n", "0", "f", "none", "ok", "undamaged"})

# Below this ratio a near-miss header is more likely coincidence than a match.
# 0.87 accepts "Suppler Name" -> vendor and rejects "Supply Region" -> vendor.
FUZZY_CUTOFF = 0.87

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


def map_columns(
    headers: list[str], *, fuzzy: bool = True
) -> tuple[dict[str, str], list[str], dict[str, float]]:
    """Map a file's headers onto canonical field names.

    Two passes, in order of confidence:

    1. **Exact alias.** ``"Unit Cost"``, ``"unit_cost"`` and ``"UNITCOST"`` all
       normalise to the same key and match outright.
    2. **Fuzzy.** Anything still unmapped is compared against every alias by
       edit-distance ratio. This is what catches the long tail of one-off
       header names — ``"Suppler Name"`` (a typo in someone's ERP export),
       ``"Delivery Ctry"``, ``"Frght Cost"`` — without needing an alias entry
       for each. The cutoff is deliberately high; a wrong mapping is far worse
       than an unmapped column, because a wrong one silently feeds the wrong
       numbers into the analytics.

    Returns ``(mapping, unmapped_headers, fuzzy_scores)`` where `fuzzy_scores`
    holds the confidence of any match made in pass 2, so the UI can show the
    user which columns were guessed rather than recognised.
    """
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

    fuzzy_scores: dict[str, float] = {}
    if fuzzy:
        for header in headers:
            if header in used:
                continue
            field_name, score = _best_fuzzy_field(header, exclude=set(mapping))
            if field_name is None:
                continue
            mapping[field_name] = header
            used.add(header)
            fuzzy_scores[field_name] = score

    unmapped = [h for h in headers if h not in used]
    return mapping, unmapped, fuzzy_scores


def _best_fuzzy_field(header: str, *, exclude: set[str]) -> tuple[str | None, float]:
    """Closest canonical field for a header, or (None, 0.0) below the cutoff."""
    normalized = _normalize_header(header)
    if len(normalized) < 3:  # "id", "to" — too short to match on shape alone
        return None, 0.0

    best_field: str | None = None
    best_score = FUZZY_CUTOFF

    for field_name, aliases in COLUMN_ALIASES.items():
        if field_name in exclude:  # already filled by an exact match
            continue
        for alias in aliases:
            score = SequenceMatcher(None, normalized, alias).ratio()
            if score > best_score:
                best_field, best_score = field_name, score

    return best_field, round(best_score, 3) if best_field else 0.0


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


# Approximate well-to-wheel emission factors, grams CO2e per tonne-kilometre,
# in the range published by GLEC/DEFRA for freight. These are rough industry
# averages, not a certified carbon calculation — the report labels any figure
# derived from them as an estimate.
CO2_FACTORS_G_PER_TONNE_KM: dict[TransportMode, float] = {
    TransportMode.AIR: 500.0,
    TransportMode.PARCEL: 150.0,
    TransportMode.ROAD: 75.0,
    TransportMode.RAIL: 25.0,
    TransportMode.OCEAN: 12.0,
    TransportMode.MULTIMODAL: 60.0,
}


def _estimate_co2(
    mode: TransportMode, distance_km: float | None, weight_kg: float | None
) -> float | None:
    """kg CO2e from mode, distance and weight — or None if any is missing.

    Returning None rather than 0.0 is the whole point: a shipment with no
    weight recorded has *unknown* emissions, and averaging zeros into a
    sustainability figure would understate it while looking authoritative.
    """
    factor = CO2_FACTORS_G_PER_TONNE_KM.get(mode)
    if factor is None or not distance_km or not weight_kg:
        return None
    tonnes = weight_kg / 1000.0
    return round(tonnes * distance_km * factor / 1000.0, 3)


def _parse_bool(raw: str | None) -> bool | None:
    """Tri-state: True, False, or None for "the file didn't say".

    None matters — a damage rate computed over rows that never carried a damage
    flag would be a fabricated zero.
    """
    if _is_null(raw):
        return None
    token = raw.strip().lower()  # type: ignore[union-attr]
    if token in TRUE_TOKENS:
        return True
    if token in FALSE_TOKENS:
        return False
    return None


def _join_place(city: str | None, country: str | None) -> str | None:
    """ "Rotterdam, NL" from its parts; whichever part exists if only one does."""
    parts = [p for p in (city, country) if p]
    return ", ".join(parts) if parts else None


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
    # original header -> match confidence, for columns matched by similarity
    # rather than by a known alias.
    fuzzy_columns: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    truncated: bool = False

    def to_report(self) -> IngestReport:
        return IngestReport(
            accepted_rows=self.accepted,
            rejected_rows=self.rejected,
            derived_delays=self.derived_delays,
            detected_columns=self.detected_columns,
            unmapped_columns=self.unmapped_columns,
            fuzzy_columns=self.fuzzy_columns,
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
        mapping, unmapped, fuzzy_scores = map_columns(headers)
        stats.detected_columns = mapping
        stats.unmapped_columns = unmapped
        stats.fuzzy_columns = {
            mapping[field_name]: score for field_name, score in fuzzy_scores.items()
        }

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
            # Exact matches only: a data row full of free text will fuzzy-match
            # something eventually, and mistaking it for the header would eat
            # the real one.
            mapping, _, _ = map_columns([cell for cell in row if cell], fuzzy=False)
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

        transit = _parse_int(value("transit_days"))
        if transit is None and shipped and actual:
            transit = max((actual - shipped).days, 0)

        status = ShipmentStatus.parse(value("status"))
        if status is ShipmentStatus.UNKNOWN and delay is not None:
            # Infer from the delay so success-rate maths isn't silently wrong.
            status = ShipmentStatus.DELAYED if delay > 0 else ShipmentStatus.ON_TIME

        # One date field drives the trend chart. Prefer when it shipped, then
        # when it arrived, then when it was due — any of them places the
        # shipment in the right month.
        occurred_on = shipped or actual or scheduled

        dest_country = _clean_str(value("destination_country"), max_length=128)
        dest_city = _clean_str(value("destination_city"), max_length=128)
        # A generic destination column wins; otherwise build one from the parts,
        # because the lane analysis needs a single label per endpoint.
        destination = _clean_str(value("destination"), max_length=255) or _join_place(
            dest_city, dest_country
        )

        quantity = _parse_int(value("quantity"))
        unit_cost = _parse_float(value("unit_cost"))
        freight = _parse_float(value("freight_cost"))
        insurance = _parse_float(value("insurance_cost"))
        duty = _parse_float(value("customs_duty"))

        total_cost = _parse_float(value("total_cost"))
        if total_cost is None:
            # Landed cost = goods + freight + insurance + duty, using whichever
            # components the file actually carries. All absent stays None.
            goods = quantity * unit_cost if quantity is not None and unit_cost is not None else None
            parts = [p for p in (goods, freight, insurance, duty) if p is not None]
            total_cost = sum(parts) if parts else None

        mode = TransportMode.parse(value("transport_mode"))
        distance = _parse_float(value("distance_km"))
        weight = _parse_float(value("weight_kg"))

        co2 = _parse_float(value("co2_kg"))
        if co2 is None:
            co2 = _estimate_co2(mode, distance, weight)

        return Shipment(
            upload_id=upload_id,
            # Identifiers
            shipment_ref=_clean_str(value("shipment_ref"), max_length=128),
            order_ref=_clean_str(value("order_ref"), max_length=128),
            tracking_number=_clean_str(value("tracking_number"), max_length=128),
            customer_ref=_clean_str(value("customer_ref"), max_length=128),
            # Parties
            vendor=_clean_str(value("vendor"), max_length=255),
            carrier=_clean_str(value("carrier"), max_length=255),
            customer=_clean_str(value("customer"), max_length=255),
            service_level=_clean_str(value("service_level"), max_length=64),
            # Product
            product=_clean_str(value("product"), max_length=255),
            sku=_clean_str(value("sku"), max_length=128),
            category=_clean_str(value("category"), max_length=128),
            brand=_clean_str(value("brand"), max_length=128),
            quantity=quantity,
            quantity_delivered=_parse_int(value("quantity_delivered")),
            unit_cost=unit_cost,
            currency=_clean_str(value("currency"), max_length=8),
            weight_kg=weight,
            hazardous=_parse_bool(value("hazardous")),
            temperature_controlled=_parse_bool(value("temperature_controlled")),
            # Geography
            origin_country=_clean_str(value("origin_country"), max_length=128),
            origin_city=_clean_str(value("origin_city"), max_length=128),
            destination=destination,
            destination_country=dest_country,
            destination_city=dest_city,
            warehouse=_clean_str(value("warehouse"), max_length=128),
            # Transport
            transport_mode=mode if mode is not TransportMode.UNKNOWN else None,
            container_ref=_clean_str(value("container_ref"), max_length=64),
            vehicle_ref=_clean_str(value("vehicle_ref"), max_length=64),
            route_ref=_clean_str(value("route_ref"), max_length=64),
            package_count=_parse_int(value("package_count")),
            distance_km=distance,
            # Timing
            lead_time_days=lead_time,
            transit_days=transit,
            delay_days=max(delay or 0, 0),  # negative "delays" are early arrivals
            status=status,
            priority=_clean_str(value("priority"), max_length=32),
            shipped_on=occurred_on,
            scheduled_delivery=scheduled,
            actual_delivery=actual,
            last_updated=_parse_date(value("last_updated")) or actual,
            # Money
            freight_cost=freight,
            insurance_cost=insurance,
            customs_duty=duty,
            total_cost=total_cost,
            # Quality
            damaged=_parse_bool(value("damaged")),
            returned=_parse_bool(value("returned")),
            # Customs
            incoterms=_clean_str(value("incoterms"), max_length=16),
            hs_code=_clean_str(value("hs_code"), max_length=32),
            # Sustainability
            co2_kg=co2,
        )
