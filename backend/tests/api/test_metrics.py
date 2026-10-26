"""Tests for the Prometheus scrape endpoint.

The failure these guard against is not a crash. It is a metric that quietly
costs more than it is worth: one time series per upload ID would work fine in
a test and take down a real Prometheus a month later.
"""

from __future__ import annotations

import uuid

import pytest

from app.core import metrics


@pytest.fixture(autouse=True)
def _clear_http_metrics():
    """Counters are process-global, so one test's traffic leaks into the next."""
    metrics.http_requests_total.clear()
    metrics.http_request_duration_seconds.clear()
    yield


async def scrape(client) -> str:
    response = await client.get("/api/v1/metrics")
    assert response.status_code == 200
    return response.text


class TestEndpoint:
    async def test_it_serves_prometheus_text_format(self, client):
        response = await client.get("/api/v1/metrics")

        assert response.status_code == 200
        # The scraper decides how to parse from the content type, not the body.
        assert "text/plain" in response.headers["content-type"]

    async def test_it_needs_no_authentication(self, client):
        # `client`, unlike `auth_client`, sends no token: a scraper runs beside
        # the service rather than logging in.
        assert (await client.get("/api/v1/metrics")).status_code == 200

    async def test_it_is_hidden_from_the_api_docs(self, client):
        schema = (await client.get("/openapi.json")).json()
        assert "/api/v1/metrics" not in schema["paths"]

    async def test_every_metric_carries_help_and_type(self, client):
        body = await scrape(client)
        for name in ("sca_http_requests_total", "sca_uploads_total"):
            assert f"# HELP {name}" in body
            assert f"# TYPE {name}" in body


class TestHttpMetrics:
    async def test_a_request_is_counted(self, client):
        await client.get("/api/v1/health")
        body = await scrape(client)

        assert 'sca_http_requests_total{method="GET"' in body
        assert 'status="200"' in body

    async def test_requests_are_labelled_by_route_template_not_path(self, client, auth_client):
        """The cardinality rule. Labelling by raw path would mint a new time
        series per upload ID, which is how a metrics backend falls over."""
        for _ in range(3):
            await auth_client.get(f"/api/v1/uploads/{uuid.uuid4()}")

        body = await scrape(client)

        assert "/api/v1/uploads/{upload_id}" in body
        # No raw UUID anywhere in the output.
        assert not any(
            len(part) == 36 and part.count("-") == 4
            for line in body.splitlines()
            for part in line.replace('"', " ").split()
        )

    async def test_unmatched_paths_share_one_series(self, client):
        """A 404 scanner must not be able to create unbounded series."""
        for path in ("/nope", "/also-nope", "/definitely/not/here"):
            await client.get(path)

        body = await scrape(client)
        unmatched = [ln for ln in body.splitlines() if 'route="unmatched"' in ln]

        assert unmatched
        assert "/also-nope" not in body

    async def test_duration_is_observed_as_a_histogram(self, client):
        await client.get("/api/v1/health")
        body = await scrape(client)

        assert "sca_http_request_duration_seconds_bucket" in body
        assert "sca_http_request_duration_seconds_count" in body


class TestDomainMetrics:
    async def test_counters_exist_before_anything_has_happened(self, client):
        """A counter that only appears after its first event makes a dashboard
        read as 'no data' rather than 'zero', which look very different."""
        body = await scrape(client)

        for name in (
            "sca_uploads_total",
            "sca_rows_ingested_total",
            "sca_delays_derived_total",
        ):
            assert name in body

    async def test_an_upload_moves_the_ingestion_counters(self, auth_client, client):
        before = metrics.rows_ingested_total._value.get()

        csv = b"vendor,delay_days,origin_country\nAcme,5,China\nBeta,0,Brazil\n"
        response = await auth_client.post(
            "/api/v1/uploads",
            files={"file": ("rows.csv", csv, "text/csv")},
        )
        assert response.status_code == 202

        assert metrics.rows_ingested_total._value.get() == before + 2
        assert "sca_rows_ingested_total" in await scrape(client)


class TestPrivacy:
    async def test_the_payload_names_no_user_or_dataset(self, auth_client, client):
        """Metrics are unauthenticated, so they must stay aggregate-only."""
        csv = b"vendor,delay_days\nSecretVendorName,4\n"
        await auth_client.post(
            "/api/v1/uploads",
            files={"file": ("confidential-q4-plan.csv", csv, "text/csv")},
        )

        body = await scrape(client)

        assert "SecretVendorName" not in body
        assert "confidential-q4-plan" not in body
        assert "@example.com" not in body
