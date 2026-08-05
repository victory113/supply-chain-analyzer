"""Unit tests for the deterministic analytics engine.

These are the tests that matter most: they pin the numbers the product reports.
No database, no network.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.models.enums import RiskLevel, ShipmentStatus
from app.services.analytics import build_report, compute_kpis, score_countries, score_vendors
from app.services.analytics.risk import compute_risk, describe_drivers
from app.services.analytics.stats import herfindahl, median, percentile, safe_div
from app.services.analytics.trends import build_trend
from tests.conftest import make_fact


class TestRiskWithMissingComponents:
    """A file that carries less data must not therefore look safer."""

    def test_an_unpriced_file_still_scores_across_the_full_range(self):
        # Same delivery performance, but no quantity or price columns.
        priced = [make_fact(delay=20) for _ in range(10)]
        unpriced = [make_fact(delay=20, quantity=0, unit_cost=0.0) for _ in range(10)]

        priced_risk = compute_risk(priced, compute_kpis(priced))
        unpriced_risk = compute_risk(unpriced, compute_kpis(unpriced))

        # Before the weights were redistributed, the unpriced file scored a
        # flat 20 points lower purely for lacking a column.
        assert unpriced_risk.score == pytest.approx(priced_risk.score, abs=1.0)

    def test_value_at_risk_is_omitted_rather_than_zeroed(self):
        unpriced = [make_fact(delay=5, quantity=0, unit_cost=0.0) for _ in range(5)]
        breakdown = compute_risk(unpriced, compute_kpis(unpriced))

        assert "value_at_risk" not in breakdown.components
        assert "value_at_risk" not in breakdown.weights

    def test_remaining_weights_still_sum_to_one(self):
        unpriced = [make_fact(delay=5, quantity=0, unit_cost=0.0) for _ in range(5)]
        breakdown = compute_risk(unpriced, compute_kpis(unpriced))
        assert sum(breakdown.weights.values()) == pytest.approx(1.0, abs=0.001)

    def test_a_priced_file_keeps_all_five_components(self):
        priced = [make_fact(delay=5) for _ in range(5)]
        breakdown = compute_risk(priced, compute_kpis(priced))
        assert "value_at_risk" in breakdown.components
        assert sum(breakdown.weights.values()) == pytest.approx(1.0, abs=0.001)


class TestStats:
    def test_safe_div_returns_default_on_zero_denominator(self):
        assert safe_div(10, 0) == 0.0
        assert safe_div(10, 0, default=1.0) == 1.0

    def test_median_odd_and_even(self):
        assert median([3, 1, 2]) == 2
        assert median([4, 1, 3, 2]) == 2.5

    def test_median_of_empty_is_zero(self):
        assert median([]) == 0.0

    def test_percentile_interpolates(self):
        # p90 of 1..10 sits between 9 and 10.
        assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 90) == pytest.approx(9.1)

    def test_percentile_single_value(self):
        assert percentile([7], 90) == 7.0

    def test_herfindahl_is_one_for_a_monopoly(self):
        assert herfindahl([1.0]) == pytest.approx(1.0)

    def test_herfindahl_is_one_over_n_when_evenly_split(self):
        assert herfindahl([0.25] * 4) == pytest.approx(0.25)


class TestKpis:
    def test_empty_dataset_returns_zeroed_summary(self):
        kpis = compute_kpis([])
        assert kpis.total_shipments == 0
        assert kpis.late_shipment_pct == 0.0
        assert kpis.delivery_success_rate == 0.0

    def test_late_percentage_and_averages(self):
        facts = [
            make_fact(delay=0),
            make_fact(delay=0),
            make_fact(delay=10),
            make_fact(delay=6),
        ]
        kpis = compute_kpis(facts)

        assert kpis.total_shipments == 4
        assert kpis.late_shipments == 2
        assert kpis.late_shipment_pct == 50.0
        assert kpis.avg_delay_days == 4.0  # (0+0+10+6)/4
        assert kpis.avg_delay_days_when_late == 8.0  # (10+6)/2

    def test_avg_lead_time_ignores_missing_values(self):
        # A None lead time must not be averaged in as a zero.
        facts = [make_fact(lead_time=10), make_fact(lead_time=None), make_fact(lead_time=20)]
        assert compute_kpis(facts).avg_lead_time_days == 15.0

    def test_value_at_risk_counts_only_at_risk_shipments(self):
        facts = [
            make_fact(delay=0, quantity=10, unit_cost=100),  # $1000 healthy
            make_fact(delay=5, quantity=10, unit_cost=100),  # $1000 at risk
        ]
        kpis = compute_kpis(facts)
        assert kpis.total_value == 2000.0
        assert kpis.value_at_risk == 1000.0

    def test_cancelled_counts_against_success_rate_even_without_delay(self):
        facts = [
            make_fact(delay=0),
            make_fact(delay=0, status=ShipmentStatus.CANCELLED),
        ]
        assert compute_kpis(facts).delivery_success_rate == 50.0


class TestVendorScoring:
    def test_perfect_vendor_scores_near_100(self):
        facts = [make_fact(vendor="Reliable", delay=0, lead_time=0) for _ in range(5)]
        score = score_vendors(facts)[0]
        assert score.health_score == 100.0
        assert score.risk_level is RiskLevel.LOW

    def test_always_late_vendor_scores_low(self):
        facts = [make_fact(vendor="Chronic", delay=30, lead_time=45) for _ in range(5)]
        score = score_vendors(facts)[0]
        assert score.health_score == 0.0
        assert score.risk_level is RiskLevel.HIGH

    def test_ranking_puts_worst_vendor_first(self):
        facts = [
            *[make_fact(vendor="Good", delay=0) for _ in range(3)],
            *[make_fact(vendor="Bad", delay=20) for _ in range(3)],
        ]
        assert score_vendors(facts)[0].vendor == "Bad"

    def test_min_shipments_filters_statistical_noise(self):
        # A single late shipment shouldn't brand a vendor as 100% unreliable.
        facts = [
            *[make_fact(vendor="Established", delay=0) for _ in range(4)],
            make_fact(vendor="OneOff", delay=30),
        ]
        vendors = {v.vendor for v in score_vendors(facts, min_shipments=2)}
        assert vendors == {"Established"}

    def test_delay_beyond_cap_does_not_push_score_negative(self):
        facts = [make_fact(vendor="Extreme", delay=400) for _ in range(3)]
        assert score_vendors(facts)[0].health_score >= 0.0


class TestCountryRisk:
    def test_country_with_no_delays_is_low_risk(self):
        facts = [make_fact(country="Canada", delay=0) for _ in range(4)]
        result = score_countries(facts)[0]
        assert result.risk_score == 0.0
        assert result.risk_level is RiskLevel.LOW

    def test_riskiest_country_sorts_first(self):
        facts = [
            *[make_fact(country="Canada", delay=0) for _ in range(3)],
            *[make_fact(country="Congo", delay=25) for _ in range(3)],
        ]
        assert score_countries(facts)[0].country == "Congo"


class TestTrends:
    def test_too_few_periods_reports_insufficient_data(self):
        facts = [make_fact(delay=5, occurred_on=date(2024, 1, 10))]
        trend = build_trend(facts)
        assert trend.direction == "insufficient_data"
        assert trend.delay_change_pct is None

    def test_rows_without_dates_are_excluded_from_the_series(self):
        facts = [make_fact(delay=1, occurred_on=None) for _ in range(5)]
        assert build_trend(facts).points == []

    def test_growing_delays_are_reported_as_worsening(self):
        facts = [
            make_fact(delay=1, occurred_on=date(2024, 1, 5)),
            make_fact(delay=1, occurred_on=date(2024, 2, 5)),
            make_fact(delay=10, occurred_on=date(2024, 3, 5)),
            make_fact(delay=12, occurred_on=date(2024, 4, 5)),
        ]
        trend = build_trend(facts)
        assert trend.direction == "worsening"
        assert trend.delay_change_pct is not None and trend.delay_change_pct > 0

    def test_shrinking_delays_are_reported_as_improving(self):
        facts = [
            make_fact(delay=12, occurred_on=date(2024, 1, 5)),
            make_fact(delay=10, occurred_on=date(2024, 2, 5)),
            make_fact(delay=1, occurred_on=date(2024, 3, 5)),
            make_fact(delay=1, occurred_on=date(2024, 4, 5)),
        ]
        assert build_trend(facts).direction == "improving"


class TestCompositeRisk:
    def test_empty_dataset_scores_zero(self):
        breakdown = compute_risk([], compute_kpis([]))
        assert breakdown.score == 0.0
        assert breakdown.level is RiskLevel.LOW

    def test_weights_sum_to_one(self):
        breakdown = compute_risk([make_fact()], compute_kpis([make_fact()]))
        assert sum(breakdown.weights.values()) == pytest.approx(1.0)

    def test_single_vendor_single_country_maxes_concentration(self):
        facts = [make_fact(vendor="Only", country="China") for _ in range(5)]
        breakdown = compute_risk(facts, compute_kpis(facts))
        assert breakdown.components["vendor_concentration"] == pytest.approx(1.0)
        assert breakdown.components["country_concentration"] == pytest.approx(1.0)

    def test_healthy_diversified_book_scores_low(self):
        facts = [make_fact(vendor=f"V{i}", country=f"C{i}", delay=0) for i in range(10)]
        assert compute_risk(facts, compute_kpis(facts)).level is RiskLevel.LOW

    def test_broken_concentrated_book_scores_high(self):
        facts = [make_fact(vendor="Only", country="China", delay=30) for _ in range(10)]
        assert compute_risk(facts, compute_kpis(facts)).level is RiskLevel.HIGH

    def test_drivers_are_ranked_by_contribution_not_raw_value(self):
        facts = [make_fact(vendor="Only", country="China", delay=30) for _ in range(10)]
        breakdown = compute_risk(facts, compute_kpis(facts))
        drivers = describe_drivers(breakdown)
        assert drivers  # non-empty
        # late_rate carries the highest weight and is maxed out here.
        assert "late" in drivers[0].lower()


class TestReport:
    def test_report_assembles_every_section(self):
        facts = [
            make_fact(vendor="A", delay=0, occurred_on=date(2024, 1, 5)),
            make_fact(vendor="A", delay=4, occurred_on=date(2024, 2, 5)),
            make_fact(vendor="B", delay=12, occurred_on=date(2024, 3, 5)),
            make_fact(vendor="B", delay=9, occurred_on=date(2024, 4, 5)),
        ]
        report = build_report("upload-1", facts)

        assert report.upload_id == "upload-1"
        assert report.kpis.total_shipments == 4
        assert report.vendors
        assert report.countries
        assert report.trend.points
        assert 0 <= report.risk.score <= 100

    def test_healthy_book_produces_healthy_signals(self):
        facts = [make_fact(vendor=f"V{i}", country=f"C{i}", delay=0) for i in range(6)]
        assert build_report("upload-1", facts).healthy_signals
