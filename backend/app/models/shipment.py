"""A normalised shipment row extracted from an uploaded CSV."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, Integer, Numeric, String
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
    )

    upload_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("uploads.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # `shipment_ref` is the customer's own identifier from the CSV — not unique
    # across uploads, and deliberately not the primary key.
    shipment_ref: Mapped[str | None] = mapped_column(String(128), index=True)
    vendor: Mapped[str | None] = mapped_column(String(255), index=True)
    product: Mapped[str | None] = mapped_column(String(255))
    origin_country: Mapped[str | None] = mapped_column(String(128), index=True)
    destination: Mapped[str | None] = mapped_column(String(255))

    quantity: Mapped[int | None] = mapped_column(Integer)
    unit_cost: Mapped[float | None] = mapped_column(Numeric(14, 4))
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    delay_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=ShipmentStatus.UNKNOWN, index=True, nullable=False
    )
    shipped_on: Mapped[date | None] = mapped_column(Date)
    last_updated: Mapped[date | None] = mapped_column(Date)

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
