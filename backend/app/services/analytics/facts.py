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

from app.models.enums import ShipmentStatus, TransportMode

if TYPE_CHECKING:
    from app.models.shipment import Shipment


def _as_float(value: object | None) -> float | None:
    """Numeric columns come back as Decimal; None must stay None."""
    return float(value) if value is not None else None  # type: ignore[arg-type]


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

    # Dimensions below are None when the upload didn't carry them. Every
    # analytic that uses one must skip the row rather than substitute a zero —
    # the difference between "this carrier was on time" and "we have no idea
    # who the carrier was" has to survive all the way to the dashboard.
    carrier: str | None = None
    transport_mode: TransportMode | None = None
    service_level: str | None = None
    category: str | None = None
    freight_cost: float | None = None
    total_cost: float | None = None
    weight_kg: float | None = None
    co2_kg: float | None = None
    damaged: bool | None = None
    returned: bool | None = None
    quantity_delivered: int | None = None

    @property
    def value(self) -> float:
        return float(self.quantity) * float(self.unit_cost)

    @property
    def lane(self) -> str:
        """Origin → destination, the unit of trade-route analysis."""
        return f"{self.origin_country} → {self.destination}"

    @property
    def fill_rate(self) -> float | None:
        """Share of the ordered quantity that actually arrived."""
        if not self.quantity or self.quantity_delivered is None:
            return None
        return min(self.quantity_delivered / self.quantity, 1.0) * 100.0

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
            # Optional dimensions stay None when absent — see the note above.
            carrier=shipment.carrier,
            transport_mode=(
                TransportMode(shipment.transport_mode) if shipment.transport_mode else None
            ),
            service_level=shipment.service_level,
            category=shipment.category,
            freight_cost=_as_float(shipment.freight_cost),
            total_cost=_as_float(shipment.total_cost),
            weight_kg=_as_float(shipment.weight_kg),
            co2_kg=_as_float(shipment.co2_kg),
            damaged=shipment.damaged,
            returned=shipment.returned,
            quantity_delivered=shipment.quantity_delivered,
        )

    @classmethod
    def from_models(cls, shipments: Iterable[Shipment]) -> list[ShipmentFact]:
        return [cls.from_model(s) for s in shipments]
