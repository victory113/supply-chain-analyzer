"""Origin-country risk scoring.

Geographic risk here is *observed*, not geopolitical: it is derived entirely
from how shipments from that origin have actually performed in the user's own
data. No external risk index is consulted, so the number is always explainable
from the uploaded file.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from app.models.enums import RiskLevel
from app.schemas.analytics import CountryRisk
from app.services.analytics.facts import DELAY_CAP_DAYS, ShipmentFact
from app.services.analytics.stats import clamp, mean, round_to, safe_div

WEIGHT_LATE_RATE = 0.60
WEIGHT_DELAY_SEVERITY = 0.40


def score_countries(facts: Sequence[ShipmentFact]) -> list[CountryRisk]:
    grouped: dict[str, list[ShipmentFact]] = defaultdict(list)
    for fact in facts:
        grouped[fact.origin_country].append(fact)

    results: list[CountryRisk] = []
    for country, rows in grouped.items():
        late = [r for r in rows if r.is_late]
        late_pct = round_to(safe_div(len(late), len(rows)) * 100)
        avg_delay = round_to(mean([float(r.delay_days) for r in rows]))

        score = round_to(
            (
                WEIGHT_LATE_RATE * (late_pct / 100.0)
                + WEIGHT_DELAY_SEVERITY * clamp(avg_delay / DELAY_CAP_DAYS)
            )
            * 100
        )

        results.append(
            CountryRisk(
                country=country,
                shipment_count=len(rows),
                late_count=len(late),
                late_pct=late_pct,
                avg_delay_days=avg_delay,
                total_value=round_to(sum(r.value for r in rows)),
                risk_score=score,
                risk_level=RiskLevel.from_score(score),
            )
        )

    results.sort(key=lambda c: (-c.risk_score, -c.total_value))
    return results


def country_shares(facts: Sequence[ShipmentFact]) -> list[float]:
    counts: dict[str, int] = defaultdict(int)
    for fact in facts:
        counts[fact.origin_country] += 1
    total = len(facts)
    return [count / total for count in counts.values()] if total else []
