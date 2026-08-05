"""Cost, quality and emissions summaries.

Each builder returns None when the upload lacks the columns to support it. That
is the difference between "your damage rate is 0%" and "this file never said
whether anything was damaged" — the first is a claim, the second is the truth,
and only one of them is safe to put on a dashboard.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.schemas.analytics import CostSummary, EmissionsSummary, QualitySummary
from app.services.analytics.facts import ShipmentFact
from app.services.analytics.stats import mean, round_to, safe_div

# A cost or quality figure drawn from a handful of rows in a large file is
# noise; below this share the column is treated as too sparse to report.
MIN_COVERAGE_PCT = 20.0
MIN_ROWS = 3


def _coverage(present: int, total: int) -> float:
    return safe_div(present, total) * 100


def build_cost_summary(facts: Sequence[ShipmentFact]) -> CostSummary | None:
    """Freight spend and what it bought."""
    if not facts:
        return None

    with_freight = [f for f in facts if f.freight_cost is not None]
    coverage = _coverage(len(with_freight), len(facts))
    if len(with_freight) < MIN_ROWS or coverage < MIN_COVERAGE_PCT:
        return None

    freight_total = sum(f.freight_cost or 0.0 for f in with_freight)
    goods_total = sum(f.value for f in with_freight)
    landed = [f.total_cost for f in facts if f.total_cost is not None]

    units = sum(f.quantity for f in with_freight if f.quantity)
    weights = [f.weight_kg for f in with_freight if f.weight_kg]

    # What the late shipments cost to move — the number that turns a delivery
    # problem into a budget conversation.
    late_freight = sum(f.freight_cost or 0.0 for f in with_freight if f.is_late)

    return CostSummary(
        coverage_pct=round_to(coverage),
        total_freight_cost=round_to(freight_total),
        avg_freight_cost=round_to(mean([f.freight_cost or 0.0 for f in with_freight])),
        freight_per_unit=round_to(safe_div(freight_total, units)) if units else None,
        freight_per_kg=round_to(safe_div(freight_total, sum(weights))) if weights else None,
        # Freight as a share of goods value: the standard "are we overpaying to
        # move cheap things?" ratio.
        freight_pct_of_goods=(
            round_to(safe_div(freight_total, goods_total) * 100) if goods_total > 0 else None
        ),
        total_landed_cost=round_to(sum(landed)) if landed else None,
        freight_spent_on_late_shipments=round_to(late_freight),
    )


def build_quality_summary(facts: Sequence[ShipmentFact]) -> QualitySummary | None:
    """Damage, returns and fill rate — only for the rows that reported them."""
    if not facts:
        return None

    damaged = [f for f in facts if f.damaged is not None]
    returned = [f for f in facts if f.returned is not None]
    fill_rates = [rate for f in facts if (rate := f.fill_rate) is not None]

    # Every component is independently optional; the section only exists if at
    # least one of them has real coverage.
    has_damage = (
        len(damaged) >= MIN_ROWS and _coverage(len(damaged), len(facts)) >= MIN_COVERAGE_PCT
    )
    has_returns = (
        len(returned) >= MIN_ROWS and _coverage(len(returned), len(facts)) >= MIN_COVERAGE_PCT
    )
    has_fill = (
        len(fill_rates) >= MIN_ROWS and _coverage(len(fill_rates), len(facts)) >= MIN_COVERAGE_PCT
    )
    if not (has_damage or has_returns or has_fill):
        return None

    return QualitySummary(
        damage_rate_pct=(
            round_to(safe_div(sum(1 for f in damaged if f.damaged), len(damaged)) * 100)
            if has_damage
            else None
        ),
        damaged_count=sum(1 for f in damaged if f.damaged) if has_damage else None,
        return_rate_pct=(
            round_to(safe_div(sum(1 for f in returned if f.returned), len(returned)) * 100)
            if has_returns
            else None
        ),
        returned_count=sum(1 for f in returned if f.returned) if has_returns else None,
        avg_fill_rate_pct=round_to(mean(fill_rates)) if has_fill else None,
        # Perfect-order rate: on time, undamaged, not returned, fully filled.
        # The composite that operations teams actually get measured on.
        perfect_order_rate_pct=round_to(_perfect_order_rate(facts) * 100),
        coverage_pct=round_to(
            _coverage(len({id(f) for f in damaged + returned}), len(facts)),
        ),
    )


def _perfect_order_rate(facts: Sequence[ShipmentFact]) -> float:
    """Share of shipments with nothing wrong that the file could tell us about.

    An unreported attribute counts as "not wrong" rather than "wrong" — the
    alternative would penalise a file for the columns it lacks.
    """
    perfect = 0
    for fact in facts:
        if fact.is_late or fact.damaged or fact.returned:
            continue
        rate = fact.fill_rate
        if rate is not None and rate < 100.0:
            continue
        perfect += 1
    return safe_div(perfect, len(facts))


def build_emissions_summary(facts: Sequence[ShipmentFact]) -> EmissionsSummary | None:
    """CO2e totals, from the file's own column or estimated from mode/distance/weight."""
    if not facts:
        return None

    with_co2 = [f for f in facts if f.co2_kg is not None]
    coverage = _coverage(len(with_co2), len(facts))
    if len(with_co2) < MIN_ROWS or coverage < MIN_COVERAGE_PCT:
        return None

    total = sum(f.co2_kg or 0.0 for f in with_co2)
    by_mode: dict[str, float] = {}
    for fact in with_co2:
        if fact.transport_mode:
            by_mode[fact.transport_mode.value] = by_mode.get(fact.transport_mode.value, 0.0) + (
                fact.co2_kg or 0.0
            )

    return EmissionsSummary(
        coverage_pct=round_to(coverage),
        total_co2_kg=round_to(total),
        avg_co2_per_shipment_kg=round_to(safe_div(total, len(with_co2))),
        co2_by_mode_kg={mode: round_to(value) for mode, value in sorted(by_mode.items())},
    )
