"""Performance breakdowns by an arbitrary dimension.

Carrier, transport mode, lane and service level all answer the same question —
"how does delivery performance differ across this dimension?" — so they share
one grouping routine rather than four near-identical ones.

Every function here returns ``[]`` when the upload didn't carry the relevant
column. That empty list is what makes the dashboard adaptive: a section with no
data is omitted entirely rather than rendered as a row of zeros.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence

from app.schemas.analytics import DimensionScore
from app.services.analytics.facts import ShipmentFact
from app.services.analytics.stats import mean, round_to, safe_div

# A dimension with only one value tells you nothing by comparison — a report
# that says "100% of your shipments went by road" is noise, not insight.
MIN_DISTINCT_VALUES = 2
# Below this a group's percentages are statistically meaningless.
MIN_SHIPMENTS_PER_GROUP = 2


def score_dimension(
    facts: Sequence[ShipmentFact],
    key: Callable[[ShipmentFact], str | None],
    *,
    min_shipments: int = MIN_SHIPMENTS_PER_GROUP,
    min_distinct: int = MIN_DISTINCT_VALUES,
) -> list[DimensionScore]:
    """Group by `key` and rank worst-performing first.

    Rows where `key` returns None are excluded rather than bucketed under
    "Unknown": they are rows the file said nothing about, and folding them into
    a real group would corrupt that group's numbers.
    """
    grouped: dict[str, list[ShipmentFact]] = defaultdict(list)
    for fact in facts:
        label = key(fact)
        if label:
            grouped[label].append(fact)

    eligible = {label: rows for label, rows in grouped.items() if len(rows) >= min_shipments}
    if len(eligible) < min_distinct:
        return []

    total_shipments = sum(len(rows) for rows in eligible.values())
    scores: list[DimensionScore] = []

    for label, rows in eligible.items():
        late = [r for r in rows if r.is_late]
        costs = [r.freight_cost for r in rows if r.freight_cost is not None]
        transit = [float(r.lead_time_days) for r in rows if r.lead_time_days is not None]

        scores.append(
            DimensionScore(
                label=label,
                shipment_count=len(rows),
                share_pct=round_to(safe_div(len(rows), total_shipments) * 100),
                late_count=len(late),
                late_pct=round_to(safe_div(len(late), len(rows)) * 100),
                avg_delay_days=round_to(mean([float(r.delay_days) for r in rows])),
                avg_transit_days=round_to(mean(transit)) if transit else None,
                total_value=round_to(sum(r.value for r in rows)),
                avg_freight_cost=round_to(mean(costs)) if costs else None,
            )
        )

    scores.sort(key=lambda d: (-d.late_pct, -d.avg_delay_days))
    return scores


def score_carriers(facts: Sequence[ShipmentFact]) -> list[DimensionScore]:
    return score_dimension(facts, lambda f: f.carrier)


def score_transport_modes(facts: Sequence[ShipmentFact]) -> list[DimensionScore]:
    return score_dimension(facts, lambda f: f.transport_mode.value if f.transport_mode else None)


def score_service_levels(facts: Sequence[ShipmentFact]) -> list[DimensionScore]:
    return score_dimension(facts, lambda f: f.service_level)


def score_categories(facts: Sequence[ShipmentFact]) -> list[DimensionScore]:
    return score_dimension(facts, lambda f: f.category)


def score_lanes(facts: Sequence[ShipmentFact], *, limit: int = 12) -> list[DimensionScore]:
    """Origin → destination routes, worst first.

    Requires both endpoints to be real: a lane of "Unknown → Unknown" is not a
    trade route, and letting it through would usually make it the largest
    "lane" in the report.
    """

    def lane_of(fact: ShipmentFact) -> str | None:
        if fact.origin_country == "Unknown" or fact.destination == "Unknown":
            return None
        return fact.lane

    return score_dimension(facts, lane_of)[:limit]
