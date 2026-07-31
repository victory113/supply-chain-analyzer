"""Time-series trend analysis over shipment dates."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from app.schemas.analytics import TrendAnalysis, TrendPoint
from app.services.analytics.facts import ShipmentFact
from app.services.analytics.stats import mean, round_to, safe_div

# Below this, a "trend" is noise. Two points can move 100% on a single shipment.
MIN_PERIODS_FOR_TREND = 3
# Ignore swings smaller than this — month-to-month jitter isn't a direction.
SIGNIFICANT_CHANGE_PCT = 10.0


def build_trend(facts: Sequence[ShipmentFact]) -> TrendAnalysis:
    buckets: dict[str, list[ShipmentFact]] = defaultdict(list)
    for fact in facts:
        period = fact.period
        if period:  # rows with no usable date simply don't appear in the series
            buckets[period].append(fact)

    points = [
        TrendPoint(
            period=period,
            shipment_count=len(rows),
            late_count=sum(1 for r in rows if r.is_late),
            late_pct=round_to(safe_div(sum(1 for r in rows if r.is_late), len(rows)) * 100),
            avg_delay_days=round_to(mean([float(r.delay_days) for r in rows])),
            total_value=round_to(sum(r.value for r in rows)),
        )
        for period, rows in sorted(buckets.items())
    ]

    if len(points) < MIN_PERIODS_FOR_TREND:
        return TrendAnalysis(
            points=points,
            direction="insufficient_data",
            delay_change_pct=None,
            commentary=(
                f"Only {len(points)} dated period(s) available; at least "
                f"{MIN_PERIODS_FOR_TREND} are needed to call a direction."
            ),
        )

    # Split the series in half and compare mean delay. More robust to a single
    # bad month than comparing the first and last points.
    midpoint = len(points) // 2
    first_half = mean([p.avg_delay_days for p in points[:midpoint]])
    second_half = mean([p.avg_delay_days for p in points[midpoint:]])

    if first_half == 0:
        change_pct = 0.0 if second_half == 0 else 100.0
    else:
        change_pct = round_to((second_half - first_half) / first_half * 100)

    if change_pct > SIGNIFICANT_CHANGE_PCT:
        direction = "worsening"
        commentary = (
            f"Average delay rose {abs(change_pct):.1f}% between the first and second "
            f"half of the period ({first_half:.1f} → {second_half:.1f} days)."
        )
    elif change_pct < -SIGNIFICANT_CHANGE_PCT:
        direction = "improving"
        commentary = (
            f"Average delay fell {abs(change_pct):.1f}% between the first and second "
            f"half of the period ({first_half:.1f} → {second_half:.1f} days)."
        )
    else:
        direction = "stable"
        commentary = (
            f"Average delay held roughly flat at {second_half:.1f} days "
            f"({change_pct:+.1f}% change)."
        )

    return TrendAnalysis(
        points=points,
        direction=direction,
        delay_change_pct=change_pct,
        commentary=commentary,
    )
