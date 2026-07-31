"""Vendor health scoring.

Each vendor gets a 0-100 health score blending three independent signals. The
weights are explicit constants so the score can be explained to a user (and
argued about in a design review) rather than being a black box.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from app.models.enums import RiskLevel
from app.schemas.analytics import VendorScore
from app.services.analytics.facts import DELAY_CAP_DAYS, LEAD_TIME_CAP_DAYS, ShipmentFact
from app.services.analytics.stats import clamp, mean, round_to, safe_div

# Punctuality dominates: a vendor that is reliably slow is easier to plan
# around than one that is unpredictably late.
WEIGHT_PUNCTUALITY = 0.50
WEIGHT_DELAY_SEVERITY = 0.30
WEIGHT_LEAD_TIME = 0.20


def _health_score(late_pct: float, avg_delay: float, avg_lead_time: float) -> float:
    punctuality = clamp(1.0 - late_pct / 100.0)
    severity = clamp(1.0 - avg_delay / DELAY_CAP_DAYS)
    lead_time = clamp(1.0 - avg_lead_time / LEAD_TIME_CAP_DAYS)
    blended = (
        WEIGHT_PUNCTUALITY * punctuality
        + WEIGHT_DELAY_SEVERITY * severity
        + WEIGHT_LEAD_TIME * lead_time
    )
    return round_to(blended * 100)


def score_vendors(facts: Sequence[ShipmentFact], *, min_shipments: int = 1) -> list[VendorScore]:
    """Rank vendors worst-first.

    ``min_shipments`` filters out one-off suppliers whose percentages are
    statistically meaningless (a single late shipment reads as 100% late).
    """
    grouped: dict[str, list[ShipmentFact]] = defaultdict(list)
    for fact in facts:
        grouped[fact.vendor].append(fact)

    scores: list[VendorScore] = []
    for vendor, rows in grouped.items():
        if len(rows) < min_shipments:
            continue

        late = [r for r in rows if r.is_late]
        late_pct = round_to(safe_div(len(late), len(rows)) * 100)
        avg_delay = round_to(mean([float(r.delay_days) for r in rows]))
        lead_times = [float(r.lead_time_days) for r in rows if r.lead_time_days is not None]
        avg_lead = round_to(mean(lead_times))
        health = _health_score(late_pct, avg_delay, avg_lead)

        scores.append(
            VendorScore(
                vendor=vendor,
                shipment_count=len(rows),
                late_count=len(late),
                late_pct=late_pct,
                avg_delay_days=avg_delay,
                avg_lead_time_days=avg_lead,
                total_value=round_to(sum(r.value for r in rows)),
                value_at_risk=round_to(sum(r.value for r in rows if r.is_at_risk)),
                health_score=health,
                # Health is inverted into a risk score so both live on the same
                # 0-100 scale as every other risk figure in the app.
                risk_level=RiskLevel.from_score(100 - health),
            )
        )

    scores.sort(key=lambda v: (v.health_score, -v.value_at_risk))
    return scores


def vendor_shares(facts: Sequence[ShipmentFact]) -> list[float]:
    """Share of total spend per vendor — the input to the concentration index."""
    totals: dict[str, float] = defaultdict(float)
    for fact in facts:
        totals[fact.vendor] += fact.value

    grand_total = sum(totals.values())
    if grand_total <= 0:
        # Fall back to shipment counts when the file has no cost data.
        counts: dict[str, int] = defaultdict(int)
        for fact in facts:
            counts[fact.vendor] += 1
        return [c / len(facts) for c in counts.values()] if facts else []

    return [value / grand_total for value in totals.values()]
