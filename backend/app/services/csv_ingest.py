"""CSV ingestion: parse, map columns, validate, normalise.

Real supply-chain exports never share a header schema, so columns are matched
by alias rather than by exact name, and unparseable *cells* degrade to null
instead of failing the whole file. A row is only rejected when it carries no
usable signal at all.
"""

from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

from app.core.config import settings
from app.core.exceptions import PayloadTooLargeError, ValidationError
from app.core.logging import get_logger
from app.models.enums import ShipmentStatus
from app.models.shipment import Shipment
from app.schemas.upload import IngestReport

logger = get_logger(__name__)

# Canonical field -> accepted header aliases (compared lowercased, non-alnum
# stripped, so "Unit Cost", "unit_cost" and "unit-cost" all match).
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "shipment_ref": ("shipmentid", "shipment", "shipmentref", "id", "ref", "ordernumber", "po"),
    "vendor": ("vendor", "supplier", "suppliername", "vendorname", "manufacturer"),
    "product": ("product", "item", "sku", "material", "description", "productname"),
    "origin_country": ("origincountry", "origin", "country", "sourcecountry", "from"),
    "destination": ("destination", "dest", "shipto", "deliverylocation", "to"),
    "quantity": ("quantity", "qty", "units", "volume", "orderqty"),
    "unit_cost": ("unitcost", "cost", "price", "unitprice", "costperunit"),
    "lead_time_days": ("leadtimedays", "leadtime", "leadtimeindays", "transitdays"),
    "delay_days": ("delaydays", "delay", "daysdelayed", "dayslate", "latedays"),
    "status": ("status", "shipmentstatus", "state", "deliverystatus"),
    "shipped_on": ("shippedon", "shipdate", "shipped", "dispatchdate", "orderdate"),
    "last_updated": ("lastupdated", "updated", "updatedat", "asof", "reportdate"),
}

DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%b-%Y", "%Y-%m-%dT%H:%M:%S")


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


def _parse_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    cleaned = raw.strip().replace(",", "").replace("_", "")
    if not cleaned:
        return None
    try:
        # float() first so "1200.0" from a spreadsheet export still parses.
        return int(float(cleaned))
    except ValueError:
        return None


def _parse_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    cleaned = raw.strip().replace(",", "").replace("$", "").replace("€", "").replace("£", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_date(raw: str | None) -> date | None:
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _clean_str(raw: str | None, *, max_length: int) -> str | None:
    if raw is None:
        return None
    cleaned = raw.strip()
    return cleaned[:max_length] if cleaned else None


@dataclass
class IngestResult:
    shipments: list[Shipment]
    report: IngestReport
    warnings: list[str] = field(default_factory=list)


class CsvIngestService:
    """Turns raw CSV bytes into validated ``Shipment`` rows."""

    def __init__(
        self,
        *,
        max_bytes: int | None = None,
        max_rows: int | None = None,
    ) -> None:
        self.max_bytes = max_bytes or settings.max_upload_bytes
        self.max_rows = max_rows or settings.max_rows_per_upload

    def parse(self, content: bytes, upload_id: uuid.UUID) -> IngestResult:
        if len(content) > self.max_bytes:
            raise PayloadTooLargeError(
                f"File is {len(content) / 1_048_576:.1f} MB; the limit is "
                f"{self.max_bytes / 1_048_576:.0f} MB."
            )

        text = self._decode(content)
        reader = csv.DictReader(io.StringIO(text))

        if not reader.fieldnames:
            raise ValidationError("The CSV has no header row.")

        headers = [h for h in reader.fieldnames if h]
        mapping, unmapped = map_columns(headers)

        if not mapping:
            raise ValidationError(
                "No recognisable supply-chain columns found.",
                details={
                    "found_headers": headers,
                    "expected_any_of": sorted(COLUMN_ALIASES),
                },
            )

        warnings: list[str] = []
        for critical in ("vendor", "delay_days", "status"):
            if critical not in mapping:
                warnings.append(
                    f"No '{critical}' column detected — metrics that depend on it "
                    "will be limited."
                )

        shipments: list[Shipment] = []
        rejected = 0

        for index, row in enumerate(reader, start=2):  # row 1 is the header
            if len(shipments) >= self.max_rows:
                warnings.append(
                    f"File truncated at {self.max_rows:,} rows; the remainder was ignored."
                )
                break

            shipment = self._build_shipment(row, mapping, upload_id)
            if shipment is None:
                rejected += 1
                if rejected <= 5:  # cap the noise on a badly-formed file
                    logger.debug("row_rejected", row_number=index)
                continue
            shipments.append(shipment)

        if not shipments:
            raise ValidationError(
                "No usable rows found. Every row was empty or missing all key fields.",
                details={"rejected_rows": rejected},
            )

        return IngestResult(
            shipments=shipments,
            report=IngestReport(
                accepted_rows=len(shipments),
                rejected_rows=rejected,
                detected_columns=mapping,
                unmapped_columns=unmapped,
                warnings=warnings,
            ),
            warnings=warnings,
        )

    @staticmethod
    def _decode(content: bytes) -> str:
        """Decode with a BOM-aware fallback chain.

        Excel exports on Windows are frequently cp1252 or UTF-8-with-BOM;
        rejecting those would fail the most common real-world upload.
        """
        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise ValidationError("File is not valid text in any supported encoding.")

    @staticmethod
    def _build_shipment(
        row: dict[str, str | None], mapping: dict[str, str], upload_id: uuid.UUID
    ) -> Shipment | None:
        def value(field_name: str) -> str | None:
            header = mapping.get(field_name)
            return row.get(header) if header else None

        vendor = _clean_str(value("vendor"), max_length=255)
        shipment_ref = _clean_str(value("shipment_ref"), max_length=128)
        product = _clean_str(value("product"), max_length=255)

        # A row with no identity at all is noise (usually a trailing blank line).
        if not any((vendor, shipment_ref, product)):
            return None

        delay = _parse_int(value("delay_days"))
        status = ShipmentStatus.parse(value("status"))

        # If the file has no status column but does record a delay, infer one so
        # downstream success-rate maths isn't silently wrong.
        if status is ShipmentStatus.UNKNOWN and delay is not None:
            status = ShipmentStatus.DELAYED if delay > 0 else ShipmentStatus.ON_TIME

        return Shipment(
            upload_id=upload_id,
            shipment_ref=shipment_ref,
            vendor=vendor,
            product=product,
            origin_country=_clean_str(value("origin_country"), max_length=128),
            destination=_clean_str(value("destination"), max_length=255),
            quantity=_parse_int(value("quantity")),
            unit_cost=_parse_float(value("unit_cost")),
            lead_time_days=_parse_int(value("lead_time_days")),
            delay_days=max(delay or 0, 0),  # negative "delays" are early arrivals
            status=status,
            shipped_on=_parse_date(value("shipped_on")),
            last_updated=_parse_date(value("last_updated")),
        )
