"""Tests for the optional analytics dimensions.

The contract under test throughout: **an absent column produces an absent
section, never a zero.** A dashboard that reports "0% damaged" for a file with
no damage column is lying, and it's the kind of lie nobody catches because it
looks like good news.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.models.enums import ShipmentStatus, TransportMode
from app.services.analytics import (
    build_cost_summary,
    build_emissions_summary,
    build_quality_summary,
    build_report,
    describe_coverage,
    score_carriers,
    score_lanes,
    score_transport_modes,
)
from app.services.analytics.facts import ShipmentFact


def fact(**overrides) -> ShipmentFact:
    base = {
        "vendor": "Acme",
        "origin_country": "China",
        "destination": "Memphis, TN",
        "product": "Widget",
        "quantity": 100,
        "unit_cost": 10.0,
        "lead_time_days": 14,
        "delay_days": 0,
        "status": ShipmentStatus.ON_TIME,
        "occurred_on": date(2024, 3, 1),
    }
    base.update(overrides)
    return ShipmentFact(**base)


class TestCarrierBreakdown:
    def test_carriers_are_ranked_worst_first(self):
        facts = [
            *[fact(carrier="SlowFreight", delay_days=10) for _ in range(4)],
            *[fact(carrier="FastShip", delay_days=0) for _ in range(4)],
        ]
        result = score_carriers(facts)
        assert [c.label for c in result] == ["SlowFreight", "FastShip"]
        assert result[0].late_pct == 100.0
        assert result[1].late_pct == 0.0

    def test_no_carrier_column_produces_no_carrier_section(self):
        assert score_carriers([fact() for _ in range(10)]) == []

    def test_a_single_carrier_is_not_reported(self):
        # "100% of shipments went with our only carrier" is not an insight.
        assert score_carriers([fact(carrier="OnlyOne") for _ in range(10)]) == []

    def test_rows_without_a_carrier_do_not_pollute_the_groups(self):
        facts = [
            *[fact(carrier="A", delay_days=0) for _ in range(3)],
            *[fact(carrier="B", delay_days=0) for _ in range(3)],
            # These have no carrier and are all late. If they leaked into a
            # group they would make a punctual carrier look terrible.
            *[fact(delay_days=30) for _ in range(20)],
        ]
        result = score_carriers(facts)
        assert {c.label for c in result} == {"A", "B"}
        assert all(c.late_pct == 0.0 for c in result)
        assert sum(c.shipment_count for c in result) == 6

    def test_shares_are_computed_over_reported_rows_only(self):
        facts = [*[fact(carrier="A") for _ in range(3)], *[fact(carrier="B") for _ in range(1)]]
        # B has only one shipment so it is excluded; A is then the only group
        # left and the whole section disappears.
        assert score_carriers(facts) == []


class TestTransportModes:
    def test_modes_are_compared(self):
        facts = [
            *[fact(transport_mode=TransportMode.AIR, delay_days=0) for _ in range(3)],
            *[fact(transport_mode=TransportMode.OCEAN, delay_days=12) for _ in range(3)],
        ]
        result = score_transport_modes(facts)
        assert [m.label for m in result] == ["ocean", "air"]
        assert result[0].avg_delay_days == 12.0


class TestLanes:
    def test_lanes_pair_origin_and_destination(self):
        facts = [
            *[fact(origin_country="China", destination="Memphis, TN") for _ in range(3)],
            *[fact(origin_country="Mexico", destination="Reno, NV") for _ in range(3)],
        ]
        labels = [lane.label for lane in score_lanes(facts)]
        assert "China → Memphis, TN" in labels
        assert "Mexico → Reno, NV" in labels

    def test_unknown_endpoints_are_not_a_lane(self):
        facts = [
            *[fact(origin_country="China", destination="Memphis, TN") for _ in range(3)],
            *[fact(origin_country="Unknown", destination="Unknown") for _ in range(30)],
        ]
        labels = [lane.label for lane in score_lanes(facts)]
        assert labels == ["China → Memphis, TN"] or labels == []
        assert not any("Unknown" in label for label in labels)


class TestCostSummary:
    def test_freight_economics_are_computed(self):
        facts = [fact(freight_cost=200.0, quantity=100, unit_cost=10.0) for _ in range(5)]
        cost = build_cost_summary(facts)
        assert cost is not None
        assert cost.total_freight_cost == 1000.0
        assert cost.avg_freight_cost == 200.0
        assert cost.freight_per_unit == 2.0
        # 1000 freight against 5000 of goods.
        assert cost.freight_pct_of_goods == 20.0

    def test_freight_spent_on_late_shipments_is_isolated(self):
        facts = [
            *[fact(freight_cost=100.0, delay_days=5) for _ in range(3)],
            *[fact(freight_cost=100.0, delay_days=0) for _ in range(3)],
        ]
        cost = build_cost_summary(facts)
        assert cost is not None
        assert cost.freight_spent_on_late_shipments == 300.0

    def test_no_cost_column_produces_no_cost_section(self):
        assert build_cost_summary([fact() for _ in range(20)]) is None

    def test_a_sparse_cost_column_is_not_extrapolated(self):
        # Two priced rows in a hundred is not a freight budget.
        facts = [*[fact(freight_cost=100.0) for _ in range(2)], *[fact() for _ in range(98)]]
        assert build_cost_summary(facts) is None


class TestQualitySummary:
    def test_damage_and_return_rates(self):
        facts = [
            *[fact(damaged=True, returned=False) for _ in range(2)],
            *[fact(damaged=False, returned=False) for _ in range(8)],
        ]
        quality = build_quality_summary(facts)
        assert quality is not None
        assert quality.damage_rate_pct == 20.0
        assert quality.damaged_count == 2
        assert quality.return_rate_pct == 0.0

    def test_no_quality_columns_produces_no_quality_section(self):
        # The heart of it: silence is not a clean bill of health.
        assert build_quality_summary([fact() for _ in range(50)]) is None

    def test_fill_rate_uses_delivered_against_ordered(self):
        facts = [fact(quantity=100, quantity_delivered=90) for _ in range(5)]
        quality = build_quality_summary(facts)
        assert quality is not None
        assert quality.avg_fill_rate_pct == 90.0

    def test_perfect_order_rate_needs_everything_to_be_right(self):
        facts = [
            fact(delay_days=0, damaged=False, returned=False, quantity=10, quantity_delivered=10),
            fact(delay_days=4, damaged=False, returned=False, quantity=10, quantity_delivered=10),
            fact(delay_days=0, damaged=True, returned=False, quantity=10, quantity_delivered=10),
            fact(delay_days=0, damaged=False, returned=False, quantity=10, quantity_delivered=5),
        ]
        quality = build_quality_summary(facts)
        assert quality is not None
        assert quality.perfect_order_rate_pct == 25.0


class TestEmissions:
    def test_totals_and_split_by_mode(self):
        facts = [
            *[fact(co2_kg=100.0, transport_mode=TransportMode.AIR) for _ in range(2)],
            *[fact(co2_kg=10.0, transport_mode=TransportMode.OCEAN) for _ in range(2)],
        ]
        emissions = build_emissions_summary(facts)
        assert emissions is not None
        assert emissions.total_co2_kg == 220.0
        assert emissions.co2_by_mode_kg == {"air": 200.0, "ocean": 20.0}

    def test_no_emissions_data_produces_no_section(self):
        assert build_emissions_summary([fact() for _ in range(20)]) is None


class TestCoverageReporting:
    def test_only_populated_dimensions_are_listed(self):
        facts = [fact(carrier="UPS", freight_cost=50.0) for _ in range(10)]
        coverage = describe_coverage(facts)
        assert "carrier" in coverage
        assert "freight_cost" in coverage
        assert "damage" not in coverage
        assert "co2" not in coverage

    def test_a_dimension_present_in_a_handful_of_rows_does_not_count(self):
        facts = [*[fact(carrier="UPS") for _ in range(2)], *[fact() for _ in range(98)]]
        assert "carrier" not in describe_coverage(facts)


class TestReportAssembly:
    def test_a_minimal_file_yields_a_report_with_no_optional_sections(self):
        facts = [fact() for _ in range(10)]
        report = build_report("upload-1", facts)

        assert report.kpis.total_shipments == 10
        assert report.carriers == []
        assert report.transport_modes == []
        assert report.cost is None
        assert report.quality is None
        assert report.emissions is None

    def test_a_rich_file_lights_up_every_section(self):
        facts = [
            *[
                fact(
                    carrier="UPS",
                    transport_mode=TransportMode.AIR,
                    service_level="Express",
                    category="Electronics",
                    freight_cost=120.0,
                    weight_kg=40.0,
                    co2_kg=88.0,
                    damaged=False,
                    returned=False,
                    quantity=100,
                    quantity_delivered=100,
                )
                for _ in range(5)
            ],
            *[
                fact(
                    carrier="DHL",
                    transport_mode=TransportMode.OCEAN,
                    service_level="Economy",
                    category="Apparel",
                    freight_cost=40.0,
                    weight_kg=60.0,
                    co2_kg=9.0,
                    damaged=True,
                    returned=True,
                    quantity=100,
                    quantity_delivered=80,
                    delay_days=6,
                )
                for _ in range(5)
            ],
        ]
        report = build_report("upload-2", facts)

        assert {c.label for c in report.carriers} == {"UPS", "DHL"}
        assert {m.label for m in report.transport_modes} == {"air", "ocean"}
        assert {s.label for s in report.service_levels} == {"Express", "Economy"}
        assert {c.label for c in report.categories} == {"Electronics", "Apparel"}
        assert report.cost is not None and report.cost.total_freight_cost == 800.0
        assert report.quality is not None and report.quality.damage_rate_pct == 50.0
        assert report.emissions is not None and report.emissions.total_co2_kg == 485.0
        assert "carrier" in report.available_dimensions


@pytest.mark.parametrize("empty", [[], ()])
class TestEmptyInput:
    def test_builders_survive_no_rows(self, empty):
        assert score_carriers(empty) == []
        assert build_cost_summary(empty) is None
        assert build_quality_summary(empty) is None
        assert build_emissions_summary(empty) is None
        assert describe_coverage(empty) == []
