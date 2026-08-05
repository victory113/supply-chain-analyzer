"""Tests for the schema-mapping layer.

This is the part of the system that lets one analytics engine serve exports
from unrelated ERP, WMS, TMS and carrier systems. Its failure modes are quiet:
a header claimed by the wrong field feeds wrong numbers into every downstream
metric, and nothing crashes.
"""

from __future__ import annotations

import pytest

from app.services.csv_ingest import COLUMN_ALIASES, FUZZY_CUTOFF, map_columns


class TestAliasTableIntegrity:
    def test_no_alias_is_claimed_by_two_fields(self):
        """A duplicate alias silently starves whichever field is declared later.

        This is exactly how `carrier` lost its column to `vendor` and `sku`
        lost its column to `product` when the model was widened.
        """
        seen: dict[str, str] = {}
        collisions: list[str] = []

        for field_name, aliases in COLUMN_ALIASES.items():
            for alias in aliases:
                if alias in seen:
                    collisions.append(f"{alias!r}: {seen[alias]} and {field_name}")
                seen[alias] = field_name

        assert collisions == []

    def test_aliases_are_already_normalised(self):
        """Aliases are compared post-normalisation, so an alias containing an
        uppercase letter or a separator can never match anything."""
        bad = [
            f"{field_name}: {alias}"
            for field_name, aliases in COLUMN_ALIASES.items()
            for alias in aliases
            if not alias.isalnum() or alias.lower() != alias
        ]
        assert bad == []

    def test_every_canonical_field_has_aliases(self):
        assert all(aliases for aliases in COLUMN_ALIASES.values())


class TestSpecificFieldsWinTheirColumns:
    """Regression guards for the collisions above."""

    def test_carrier_column_goes_to_carrier_not_vendor(self):
        mapping, _, _ = map_columns(["Supplier", "Carrier"])
        assert mapping["vendor"] == "Supplier"
        assert mapping["carrier"] == "Carrier"

    def test_sku_and_brand_are_not_swallowed_by_product(self):
        mapping, _, _ = map_columns(["Product Name", "SKU", "Brand", "Category"])
        assert mapping["product"] == "Product Name"
        assert mapping["sku"] == "SKU"
        assert mapping["brand"] == "Brand"
        assert mapping["category"] == "Category"

    def test_tracking_number_is_not_swallowed_by_shipment_ref(self):
        mapping, _, _ = map_columns(["Shipment ID", "Tracking Number"])
        assert mapping["shipment_ref"] == "Shipment ID"
        assert mapping["tracking_number"] == "Tracking Number"

    def test_destination_parts_map_to_their_own_fields(self):
        mapping, _, _ = map_columns(["Destination City", "Destination Country"])
        assert mapping["destination_city"] == "Destination City"
        assert mapping["destination_country"] == "Destination Country"


class TestFuzzyMatching:
    @pytest.mark.parametrize(
        ("header", "expected"),
        [
            ("Suppler Name", "vendor"),  # typo in the source system
            ("Freigt Cost", "freight_cost"),
            ("Carrier Nmae", "carrier"),
            ("Quantiy", "quantity"),
        ],
    )
    def test_near_misses_are_recovered(self, header: str, expected: str):
        mapping, unmapped, fuzzy = map_columns([header])
        assert mapping.get(expected) == header
        assert unmapped == []
        assert fuzzy[expected] >= FUZZY_CUTOFF

    def test_a_fuzzy_match_is_reported_as_a_guess(self):
        # The user has to be able to tell a guess from a recognised column.
        _, _, fuzzy = map_columns(["Suppler Name", "Carrier"])
        assert "vendor" in fuzzy
        assert "carrier" not in fuzzy  # exact match, not a guess

    @pytest.mark.parametrize(
        "header",
        [
            "Internal Notes",
            "Approver",
            "Comments",
            "Department Budget Code",
        ],
    )
    def test_unrelated_columns_are_left_alone(self, header: str):
        # A wrong mapping is worse than no mapping: it feeds bad data into the
        # metrics without any signal that it happened.
        mapping, unmapped, _ = map_columns([header])
        assert mapping == {}
        assert unmapped == [header]

    def test_very_short_headers_are_not_fuzzy_matched(self):
        # Two-character headers match far too much on shape alone.
        mapping, unmapped, _ = map_columns(["Qy", "Xx"])
        assert mapping == {}
        assert len(unmapped) == 2

    def test_fuzzy_can_be_disabled(self):
        mapping, unmapped, fuzzy = map_columns(["Suppler Name"], fuzzy=False)
        assert mapping == {}
        assert unmapped == ["Suppler Name"]
        assert fuzzy == {}

    def test_exact_matches_are_never_overridden_by_fuzzy(self):
        mapping, _, fuzzy = map_columns(["Vendor", "Vendr Name"])
        assert mapping["vendor"] == "Vendor"
        assert fuzzy == {} or "vendor" not in fuzzy
