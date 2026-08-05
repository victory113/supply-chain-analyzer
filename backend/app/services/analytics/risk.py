"""Composite supply-chain risk score.

Five weighted components on a 0-1 scale, blended into a single 0-100 figure.
Both the components and the weights are returned alongside the score so the
dashboard can show *why* a number moved, and so the LLM can cite the driver
rather than inventing one.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.models.enums import RiskLevel
from app.schemas.analytics import KpiSummary, RiskBreakdown
from app.services.analytics.countries import country_shares
from app.services.analytics.facts import DELAY_CAP_DAYS, ShipmentFact
from app.services.analytics.stats import clamp, herfindahl, round_to, safe_div
from app.services.analytics.vendors import vendor_shares

WEIGHTS: dict[str, float] = {
    "late_rate": 0.30,
    "delay_severity": 0.25,
    "value_at_risk": 0.20,
    "vendor_concentration": 0.15,
    "country_concentration": 0.10,
}


def compute_risk(facts: Sequence[ShipmentFact], kpis: KpiSummary) -> RiskBreakdown:
    if not facts:
        return RiskBreakdown(
            score=0.0,
            level=RiskLevel.LOW,
            components=dict.fromkeys(WEIGHTS, 0.0),
            weights=dict(WEIGHTS),
        )

    components: dict[str, float] = {
        # How often things go wrong.
        "late_rate": clamp(kpis.late_shipment_pct / 100.0),
        # How badly, when they do.
        "delay_severity": clamp(kpis.avg_delay_days / DELAY_CAP_DAYS),
        # Single-supplier and single-origin dependency.
        "vendor_concentration": clamp(herfindahl(vendor_shares(facts))),
        "country_concentration": clamp(herfindahl(country_shares(facts))),
    }

    # Money exposure is only a component when the file priced anything. Scoring
    # it as 0.0 otherwise would be a silent 20-point discount for uploads with
    # no cost column: the same supply chain would look safer purely because it
    # told us less. Instead the weight is redistributed over what we *can*
    # measure, so every score is a full 0-100 regardless of file shape.
    if kpis.total_value > 0:
        components["value_at_risk"] = clamp(safe_div(kpis.value_at_risk, kpis.total_value))

    weights = _renormalise({key: WEIGHTS[key] for key in components})
    score = round_to(sum(components[key] * weight for key, weight in weights.items()) * 100)

    return RiskBreakdown(
        score=score,
        level=RiskLevel.from_score(score),
        components={k: round_to(v, 4) for k, v in components.items()},
        weights={k: round_to(v, 4) for k, v in weights.items()},
    )


def _renormalise(active: dict[str, float]) -> dict[str, float]:
    """Scale a subset of the weights back up to sum to 1.0."""
    total = sum(active.values())
    if total <= 0:
        return active
    return {key: weight / total for key, weight in active.items()}


def describe_drivers(breakdown: RiskBreakdown, *, top_n: int = 3) -> list[str]:
    """Rank components by their *contribution* (component x weight).

    A component can be high but barely matter if its weight is small; ranking
    on the product is what tells a user where to actually intervene.
    """
    labels = {
        "late_rate": "share of shipments running late",
        "delay_severity": "average delay length",
        "value_at_risk": "order value tied up in at-risk shipments",
        "vendor_concentration": "dependency on a small number of vendors",
        "country_concentration": "dependency on a small number of origin countries",
    }
    contributions = sorted(
        (
            (key, breakdown.components.get(key, 0.0) * weight)
            for key, weight in breakdown.weights.items()
        ),
        key=lambda pair: pair[1],
        reverse=True,
    )
    return [
        f"{labels.get(key, key)} (contributes {value * 100:.1f} of {breakdown.score:.1f})"
        for key, value in contributions[:top_n]
        if value > 0
    ]
