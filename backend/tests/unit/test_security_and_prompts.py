"""Unit tests for password hashing, JWT handling, and prompt construction."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.exceptions import AuthenticationError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.services.analytics import build_report
from app.services.chat import route_intent
from app.services.prompts import build_analysis_prompt, build_metrics_brief
from tests.conftest import make_fact


class TestPasswordHashing:
    def test_hash_is_salted_so_the_same_password_hashes_differently(self):
        assert hash_password("correct horse") != hash_password("correct horse")

    def test_verify_accepts_the_right_password(self):
        assert verify_password("correct horse", hash_password("correct horse"))

    def test_verify_rejects_the_wrong_password(self):
        assert not verify_password("wrong horse", hash_password("correct horse"))

    def test_verify_returns_false_on_a_malformed_hash_instead_of_raising(self):
        # A corrupted row must fail the login, not 500 the endpoint.
        assert not verify_password("anything", "not-a-bcrypt-hash")

    def test_password_over_the_bcrypt_limit_is_rejected_loudly(self):
        # bcrypt silently truncates past 72 bytes; silent truncation would mean
        # two different long passwords authenticate the same account.
        with pytest.raises(ValueError, match="72-byte"):
            hash_password("x" * 100)


class TestJwt:
    def test_round_trip_preserves_the_subject(self):
        token = create_access_token("user-123", email="a@b.com")
        payload = decode_access_token(token)
        assert payload["sub"] == "user-123"
        assert payload["email"] == "a@b.com"

    def test_expired_token_is_rejected(self):
        token = create_access_token("user-123", expires_delta=timedelta(seconds=-10))
        with pytest.raises(AuthenticationError, match="expired"):
            decode_access_token(token)

    def test_tampered_token_is_rejected(self):
        token = create_access_token("user-123")
        with pytest.raises(AuthenticationError, match="invalid"):
            decode_access_token(token + "x")

    def test_each_token_has_a_unique_id(self):
        first = decode_access_token(create_access_token("u"))
        second = decode_access_token(create_access_token("u"))
        assert first["jti"] != second["jti"]


@pytest.fixture
def report():
    facts = [
        make_fact(vendor="Acme", country="China", delay=8, occurred_on=date(2024, 1, 5)),
        make_fact(vendor="Acme", country="China", delay=6, occurred_on=date(2024, 2, 5)),
        make_fact(vendor="Beta", country="Brazil", delay=0, occurred_on=date(2024, 3, 5)),
        make_fact(vendor="Beta", country="Brazil", delay=0, occurred_on=date(2024, 4, 5)),
    ]
    return build_report("upload-1", facts)


class TestPrompts:
    def test_brief_contains_the_computed_kpis(self, report):
        brief = build_metrics_brief(report)
        assert "late_shipment_pct" in brief
        assert "composite_score" in brief
        assert str(report.kpis.total_shipments) in brief

    def test_brief_names_the_vendors_and_countries(self, report):
        brief = build_metrics_brief(report)
        assert "Acme" in brief
        assert "China" in brief

    def test_analysis_prompt_asks_for_an_evidence_metric(self, report):
        assert "evidence_metric" in build_analysis_prompt(report)

    def test_brief_carries_no_raw_shipment_rows(self, report):
        # The model must reason over aggregates, not the underlying records.
        brief = build_metrics_brief(report)
        assert "shipment_ref" not in brief
        assert "Dallas TX" not in brief

    def test_lane_labels_are_withheld_from_the_model(self, report):
        """Destinations are the likeliest place for a customer name or street
        address to appear, so lane analysis stays on our side of the wire even
        though the lanes themselves are computed and shown in the UI."""
        brief = build_metrics_brief(report)
        assert "Dallas TX" not in brief
        assert all(lane.label not in brief for lane in report.lanes)


class TestChatIntentRouting:
    def test_vendor_question_selects_the_vendor_section(self):
        assert "vendors" in route_intent("Which supplier is worst?")

    def test_geography_question_selects_the_country_section(self):
        assert "countries" in route_intent("Which origin country is riskiest?")

    def test_temporal_question_selects_the_trend_section(self):
        assert "trend" in route_intent("Why are delays increasing this year?")

    def test_kpis_and_risk_are_always_included(self):
        sections = route_intent("something completely unrelated")
        assert {"kpis", "risk"} <= sections
