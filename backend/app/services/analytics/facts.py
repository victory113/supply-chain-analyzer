"""The input record for the analytics engine.

The engine works on plain frozen dataclasses rather than ORM instances so
every metric can be unit-tested without a database, and so the scoring logic
has no import-time dependency on SQLAlchemy.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from app.models.enums import ShipmentStatus

if TYPE_CHECKING:
    from app.models.shipment import Shipment

# Delays beyond this are treated as equally catastrophic. Without a cap, one
# 400-day outlier would dominate every average and flatten the scoring range.
DELAY_CAP_DAYS = 21.0
LEAD_TIME_CAP_DAYS = 45.0

_UNHEALTHY = {ShipmentStatus.DELAYED, ShipmentStatus.CRITICAL, ShipmentStatus.CANCELLED}


@dataclass(frozen=True, slots=True)
class ShipmentFact:
    vendor: str
    origin_country: str
    destination: str
    product: str
    quantity: int
    unit_cost: float
    lead_time_days: int | None
    delay_days: int
    status: ShipmentStatus
    occurred_on: date | None

    @property
    def value(self) -> float:
        return float(self.quantity) * float(self.unit_cost)

    @property
    def is_late(self) -> bool:
        return self.delay_days > 0

    @property
    def is_at_risk(self) -> bool:
        return self.is_late or self.status in _UNHEALTHY

    @property
    def is_successful(self) -> bool:
        return not self.is_at_risk

    @property
    def period(self) -> str | None:
        """ISO year-month bucket used by the trend series."""
        return self.occurred_on.strftime("%Y-%m") if self.occurred_on else None

    @classmethod
    def from_model(cls, shipment: Shipment) -> ShipmentFact:
        return cls(
            vendor=shipment.vendor or "Unknown vendor",
            origin_country=shipment.origin_country or "Unknown",
            destination=shipment.destination or "Unknown",
            product=shipment.product or "Unknown",
            quantity=shipment.quantity or 0,
            unit_cost=float(shipment.unit_cost) if shipment.unit_cost is not None else 0.0,
            lead_time_days=shipment.lead_time_days,
            delay_days=shipment.delay_days or 0,
            status=ShipmentStatus(shipment.status),
            occurred_on=shipment.shipped_on or shipment.last_updated,
        )

    @classmethod
    def from_models(cls, shipments: Iterable[Shipment]) -> list[ShipmentFact]:
        return [cls.from_model(s) for s in shipments]
