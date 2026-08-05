"""Upload and shipment schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.enums import ShipmentStatus, UploadStatus
from app.schemas.common import ORMModel


class UploadRead(ORMModel):
    id: uuid.UUID
    filename: str
    label: str | None
    size_bytes: int
    row_count: int
    rejected_row_count: int
    status: UploadStatus
    error_message: str | None
    created_at: datetime


class IngestReport(BaseModel):
    """What the parser made of the file — returned so users can fix bad exports."""

    accepted_rows: int
    rejected_rows: int
    # Rows whose delay the app computed from a date pair rather than read from
    # a column. Reported so an invented number never looks like a supplied one.
    derived_delays: int = 0
    detected_columns: dict[str, str]
    unmapped_columns: list[str]
    # Headers matched by similarity rather than a known alias, with confidence.
    # Shown separately so a guess is never presented as a recognised column.
    fuzzy_columns: dict[str, float] = {}
    warnings: list[str] = []


class UploadAccepted(BaseModel):
    """202 response: the CSV is stored, the AI analysis is queued."""

    upload: UploadRead
    analysis_id: uuid.UUID
    task_id: str | None
    poll_url: str
    # What the parser made of the file: which columns it recognised, which it
    # ignored, and what it had to derive. Shown to the user immediately, before
    # the AI narration arrives.
    ingest: IngestReport | None = None


class ShipmentRead(ORMModel):
    id: uuid.UUID
    shipment_ref: str | None
    vendor: str | None
    product: str | None
    origin_country: str | None
    destination: str | None
    quantity: int | None
    unit_cost: float | None
    lead_time_days: int | None
    delay_days: int
    status: ShipmentStatus
    shipped_on: date | None
    last_updated: date | None
