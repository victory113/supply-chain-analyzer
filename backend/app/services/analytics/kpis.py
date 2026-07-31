"""Headline KPIs, computed in Python from the stored shipment rows."""

from __future__ import annotations

from collections.abc import Sequence

from app.schemas.analytics import KpiSummary
from app.services.analytics.facts import ShipmentFact
from app.services.analytics.stats import mean, median, percentile, round_to, safe_div


def compute_kpis(facts: Sequence[ShipmentFact]) -> KpiSummary:
    total = len(facts)
    if total == 0:
        return KpiSummary(
            total_shipments=0,
            late_shipments=0,
            late_shipment_pct=0.0,
            avg_delay_days=0.0,
            avg_delay_days_when_late=0.0,
            median_delay_days=0.0,
            p90_delay_days=0.0,
            avg_lead_time_days=0.0,
            delivery_success_rate=0.0,
            total_value=0.0,
            value_at_risk=0.0,
            distinct_vendors=0,
            distinct_countries=0,
        )

    delays = [float(f.delay_days) for f in facts]
    late = [f for f in facts if f.is_late]
    # Only shipments that actually carry a lead time — averaging in zeros for
    # missing values would understate the real lead time.
    lead_times = [float(f.lead_time_days) for f in facts if f.lead_time_days is not None]

    return KpiSummary(
        total_shipments=total,
        late_shipments=len(late),
        late_shipment_pct=round_to(safe_div(len(late), total) * 100),
        avg_delay_days=round_to(mean(delays)),
        avg_delay_days_when_late=round_to(mean([float(f.delay_days) for f in late])),
        median_delay_days=round_to(median(delays)),
        p90_delay_days=round_to(percentile(delays, 90)),
        avg_lead_time_days=round_to(mean(lead_times)),
        delivery_success_rate=round_to(
            safe_div(sum(1 for f in facts if f.is_successful), total) * 100
        ),
        total_value=round_to(sum(f.value for f in facts)),
        value_at_risk=round_to(sum(f.value for f in facts if f.is_at_risk)),
        distinct_vendors=len({f.vendor for f in facts}),
        distinct_countries=len({f.origin_country for f in facts}),
    )
