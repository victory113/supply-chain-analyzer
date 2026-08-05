"""The canonical shipment record.

Uploads arrive from ERP, WMS, TMS and carrier systems that agree on nothing,
so ingestion maps whatever columns a file happens to have onto *this* shape and
the analytics engine only ever sees this shape. Adding support for a new export
format is therefore an alias change, never an analytics change.

Every field below is optional except `upload_id`, `delay_days` and `status`.
That is deliberate: a file carrying nothing but a country and a delay is still
analysable, and a field the source didn't provide must stay NULL rather than
default to zero — a zero is a measurement, and claiming one we never took is
the failure mode this model exists to prevent.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import GUID, Base, TimestampMixin
from app.models.enums import ShipmentStatus

if TYPE_CHECKING:
    from app.models.upload import Upload


class Shipment(Base, TimestampMixin):
    __tablename__ = "shipments"
    __table_args__ = (
        # The dashboard filters by vendor and by country within an upload;
        # these two composites cover every query the analytics engine issues.
        Index("ix_shipments_upload_vendor", "upload_id", "vendor"),
        Index("ix_shipments_upload_country", "upload_id", "origin_country"),
        Index("ix_shipments_upload_carrier", "upload_id", "carrier"),
    )

    upload_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("uploads.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # ── Identifiers ───────────────────────────────────────────────────
    # `shipment_ref` is the customer's own identifier from the CSV — not unique
    # across uploads, and deliberately not the primary key.
    shipment_ref: Mapped[str | None] = mapped_column(String(128), index=True)
    order_ref: Mapped[str | None] = mapped_column(String(128))
    tracking_number: Mapped[str | None] = mapped_column(String(128))
    customer_ref: Mapped[str | None] = mapped_column(String(128))

    # ── Parties ───────────────────────────────────────────────────────
    vendor: Mapped[str | None] = mapped_column(String(255), index=True)
    carrier: Mapped[str | None] = mapped_column(String(255))
    customer: Mapped[str | None] = mapped_column(String(255))
    service_level: Mapped[str | None] = mapped_column(String(64))

    # ── Product ───────────────────────────────────────────────────────
    product: Mapped[str | None] = mapped_column(String(255))
    sku: Mapped[str | None] = mapped_column(String(128))
    category: Mapped[str | None] = mapped_column(String(128))
    brand: Mapped[str | None] = mapped_column(String(128))
    quantity: Mapped[int | None] = mapped_column(Integer)
    quantity_delivered: Mapped[int | None] = mapped_column(Integer)
    unit_cost: Mapped[float | None] = mapped_column(Numeric(14, 4))
    currency: Mapped[str | None] = mapped_column(String(8))
    weight_kg: Mapped[float | None] = mapped_column(Numeric(14, 3))
    hazardous: Mapped[bool | None] = mapped_column(Boolean)
    temperature_controlled: Mapped[bool | None] = mapped_column(Boolean)

    # ── Geography ─────────────────────────────────────────────────────
    origin_country: Mapped[str | None] = mapped_column(String(128), index=True)
    origin_city: Mapped[str | None] = mapped_column(String(128))
    destination: Mapped[str | None] = mapped_column(String(255))
    destination_country: Mapped[str | None] = mapped_column(String(128))
    destination_city: Mapped[str | None] = mapped_column(String(128))
    warehouse: Mapped[str | None] = mapped_column(String(128))

    # ── Transport ─────────────────────────────────────────────────────
    transport_mode: Mapped[str | None] = mapped_column(String(32), index=True)
    container_ref: Mapped[str | None] = mapped_column(String(64))
    vehicle_ref: Mapped[str | None] = mapped_column(String(64))
    route_ref: Mapped[str | None] = mapped_column(String(64))
    package_count: Mapped[int | None] = mapped_column(Integer)
    distance_km: Mapped[float | None] = mapped_column(Numeric(12, 2))

    # ── Timing ────────────────────────────────────────────────────────
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    transit_days: Mapped[int | None] = mapped_column(Integer)
    delay_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=ShipmentStatus.UNKNOWN, index=True, nullable=False
    )
    priority: Mapped[str | None] = mapped_column(String(32))
    shipped_on: Mapped[date | None] = mapped_column(Date)
    # Kept alongside the derived `delay_days` so the derivation stays auditable:
    # a user can see the two dates the number came from.
    scheduled_delivery: Mapped[date | None] = mapped_column(Date)
    actual_delivery: Mapped[date | None] = mapped_column(Date)
    last_updated: Mapped[date | None] = mapped_column(Date)

    # ── Money ─────────────────────────────────────────────────────────
    freight_cost: Mapped[float | None] = mapped_column(Numeric(14, 4))
    insurance_cost: Mapped[float | None] = mapped_column(Numeric(14, 4))
    customs_duty: Mapped[float | None] = mapped_column(Numeric(14, 4))
    total_cost: Mapped[float | None] = mapped_column(Numeric(14, 4))

    # ── Quality ───────────────────────────────────────────────────────
    damaged: Mapped[bool | None] = mapped_column(Boolean)
    returned: Mapped[bool | None] = mapped_column(Boolean)

    # ── Customs ───────────────────────────────────────────────────────
    incoterms: Mapped[str | None] = mapped_column(String(16))
    hs_code: Mapped[str | None] = mapped_column(String(32))

    # ── Sustainability ────────────────────────────────────────────────
    co2_kg: Mapped[float | None] = mapped_column(Numeric(14, 3))

    upload: Mapped[Upload] = relationship(back_populates="shipments")

    @property
    def total_value(self) -> float:
        if self.quantity is None or self.unit_cost is None:
            return 0.0
        return float(self.quantity) * float(self.unit_cost)

    @property
    def is_late(self) -> bool:
        return self.delay_days > 0

    def __repr__(self) -> str:
        return f"<Shipment {self.shipment_ref} {self.vendor} +{self.delay_days}d>"
