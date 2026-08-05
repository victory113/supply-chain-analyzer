"""Analytics engine entry point.

Everything here is deterministic Python: the same rows always produce the same
numbers. Claude is handed this report and asked to *explain* it — it never
computes any figure the user sees.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from app.schemas.analytics import (
    AnalyticsReport,
    HistoricalPoint,
    HistoricalReport,
)
from app.services.analytics.countries import score_countries
from app.services.analytics.dimensions import (
    score_carriers,
    score_categories,
    score_lanes,
    score_service_levels,
    score_transport_modes,
)
from app.services.analytics.facts import ShipmentFact
from app.services.analytics.kpis import compute_kpis
from app.services.analytics.operations import (
    build_cost_summary,
    build_emissions_summary,
    build_quality_summary,
)
from app.services.analytics.risk import compute_risk
from app.services.analytics.stats import mean, round_to
from app.services.analytics.trends import build_trend
from app.services.analytics.vendors import score_vendors

# Thresholds for calling something out as genuinely healthy rather than
# merely not-terrible.
GOOD_SUCCESS_RATE = 85.0
GOOD_LATE_RATE = 15.0
GOOD_AVG_DELAY = 3.0
MIN_VENDORS_FOR_DIVERSITY = 3
MIN_COUNTRIES_FOR_DIVERSITY = 3
STRONG_VENDOR_HEALTH = 85.0


def build_report(upload_id: str, facts: Sequence[ShipmentFact]) -> AnalyticsReport:
    """Compute every metric the uploaded columns can support — and only those.

    The optional sections are the reason this app can accept an export from any
    system: a file with a carrier column gets carrier analysis, one without
    simply doesn't, and neither case requires the caller to know in advance.
    """
    kpis = compute_kpis(facts)
    return AnalyticsReport(
        upload_id=upload_id,
        kpis=kpis,
        # min_shipments=2 keeps single-order suppliers out of the ranking, where
        # one late delivery would otherwise read as a 100% failure rate.
        vendors=score_vendors(facts, min_shipments=2),
        countries=score_countries(facts),
        trend=build_trend(facts),
        risk=compute_risk(facts, kpis),
        healthy_signals=find_healthy_signals(facts),
        carriers=score_carriers(facts),
        transport_modes=score_transport_modes(facts),
        service_levels=score_service_levels(facts),
        categories=score_categories(facts),
        lanes=score_lanes(facts),
        cost=build_cost_summary(facts),
        quality=build_quality_summary(facts),
        emissions=build_emissions_summary(facts),
        available_dimensions=describe_coverage(facts),
    )


# Canonical field -> how to tell whether a row populated it. Drives the
# "what else could this file have told us?" hint in the UI.
_COVERAGE_PROBES: dict[str, Callable[[ShipmentFact], bool]] = {
    "carrier": lambda f: f.carrier is not None,
    "transport_mode": lambda f: f.transport_mode is not None,
    "service_level": lambda f: f.service_level is not None,
    "category": lambda f: f.category is not None,
    "freight_cost": lambda f: f.freight_cost is not None,
    "weight": lambda f: f.weight_kg is not None,
    "co2": lambda f: f.co2_kg is not None,
    "damage": lambda f: f.damaged is not None,
    "returns": lambda f: f.returned is not None,
    "fill_rate": lambda f: f.quantity_delivered is not None,
}


def describe_coverage(facts: Sequence[ShipmentFact], *, min_share: float = 0.2) -> list[str]:
    """Optional dimensions this upload actually carries, in a stable order."""
    if not facts:
        return []
    threshold = len(facts) * min_share
    return [
        name
        for name, probe in _COVERAGE_PROBES.items()
        if sum(1 for f in facts if probe(f)) >= threshold
    ]


def find_healthy_signals(facts: Sequence[ShipmentFact]) -> list[str]:
    """Deterministic positives — what is demonstrably working."""
    if not facts:
        return []

    kpis = compute_kpis(facts)
    signals: list[str] = []

    if kpis.delivery_success_rate >= GOOD_SUCCESS_RATE:
        signals.append(
            f"{kpis.delivery_success_rate:.1f}% of shipments arrived without a delay flag."
        )
    if kpis.late_shipment_pct <= GOOD_LATE_RATE:
        signals.append(f"Only {kpis.late_shipment_pct:.1f}% of shipments ran late.")
    if kpis.avg_delay_days <= GOOD_AVG_DELAY:
        signals.append(f"Average delay is {kpis.avg_delay_days:.1f} days across the book.")
    if kpis.distinct_vendors >= MIN_VENDORS_FOR_DIVERSITY:
        signals.append(
            f"Supply is spread across {kpis.distinct_vendors} vendors, "
            "limiting single-supplier exposure."
        )
    if kpis.distinct_countries >= MIN_COUNTRIES_FOR_DIVERSITY:
        signals.append(f"Sourcing spans {kpis.distinct_countries} origin countries.")

    strong = [
        v for v in score_vendors(facts, min_shipments=2) if v.health_score >= STRONG_VENDOR_HEALTH
    ]
    if strong:
        names = ", ".join(v.vendor for v in strong[:3])
        signals.append(f"Consistently reliable vendors: {names}.")

    trend = build_trend(facts)
    if trend.direction == "improving":
        signals.append(trend.commentary)

    return signals


def build_historical_report(
    points: list[HistoricalPoint], *, significant_change_pct: float = 10.0
) -> HistoricalReport:
    """Compare uploads over time — the 'how did the last year go?' view.

    Takes pre-computed per-upload summaries rather than raw shipments so the
    caller can pull them from stored analyses instead of re-scanning every row.
    """
    if len(points) < 2:
        return HistoricalReport(
            points=points,
            direction="insufficient_data",
            summary="Upload at least two datasets to see how performance is trending.",
        )

    midpoint = len(points) // 2
    early = mean([p.risk_score for p in points[:midpoint]])
    recent = mean([p.risk_score for p in points[midpoint:]])
    delta = round_to(recent - early)

    if delta > significant_change_pct * 0.1:
        direction = "worsening"
    elif delta < -significant_change_pct * 0.1:
        direction = "improving"
    else:
        direction = "stable"

    first, last = points[0], points[-1]
    summary = (
        f"Across {len(points)} uploads, the composite risk score moved from "
        f"{first.risk_score:.1f} to {last.risk_score:.1f} ({delta:+.1f} on average, "
        f"{direction}). Late-shipment rate went from {first.late_shipment_pct:.1f}% "
        f"to {last.late_shipment_pct:.1f}%, and average delay from "
        f"{first.avg_delay_days:.1f} to {last.avg_delay_days:.1f} days."
    )

    return HistoricalReport(points=points, direction=direction, summary=summary)
