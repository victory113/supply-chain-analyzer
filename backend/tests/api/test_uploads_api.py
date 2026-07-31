"""API tests for upload ingestion, tenant isolation, and analytics endpoints."""

from __future__ import annotations

import pytest

SAMPLE_CSV = b"""shipment_id,vendor,product,origin_country,destination,quantity,unit_cost,lead_time_days,status,delay_days,shipped_on
S001,GlobalParts,Boards,China,Dallas TX,500,45.00,14,delayed,8,2024-01-15
S002,FastShip,Rods,Brazil,Houston TX,1200,12.50,7,on_time,0,2024-02-15
S003,GlobalParts,Chips,Taiwan,Austin TX,250,120.00,21,delayed,15,2024-03-14
S004,QuickSupply,Foam,Mexico,Dallas TX,3000,2.10,3,on_time,0,2024-04-15
"""


async def upload_csv(client, content: bytes = SAMPLE_CSV, name: str = "data.csv"):
    return await client.post(
        "/api/v1/uploads",
        files={"file": (name, content, "text/csv")},
        data={"label": "Q1 export"},
    )


class TestUploadCreation:
    async def test_upload_is_accepted_and_an_analysis_is_queued(self, auth_client):
        response = await upload_csv(auth_client)
        assert response.status_code == 202

        body = response.json()
        assert body["upload"]["row_count"] == 4
        assert body["upload"]["status"] == "analyzing"
        assert body["analysis_id"]
        assert body["poll_url"].endswith("/status")

    async def test_upload_requires_authentication(self, client):
        response = await upload_csv(client)
        assert response.status_code == 401

    async def test_non_csv_extension_is_rejected(self, auth_client):
        response = await upload_csv(auth_client, name="data.xlsx")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    async def test_file_with_no_supply_chain_columns_is_rejected(self, auth_client):
        response = await upload_csv(auth_client, content=b"alpha,beta\n1,2\n")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    async def test_rejected_rows_are_reported_not_hidden(self, auth_client):
        csv = b"vendor,delay_days\nAcme,3\n,\n,\n"
        body = (await upload_csv(auth_client, content=csv)).json()
        assert body["upload"]["row_count"] == 1
        assert body["upload"]["rejected_row_count"] == 2


class TestUploadListing:
    async def test_listing_is_paginated(self, auth_client):
        for _ in range(3):
            await upload_csv(auth_client)

        response = await auth_client.get("/api/v1/uploads?limit=2&offset=0")
        body = response.json()
        assert len(body["items"]) == 2
        assert body["total"] == 3

    async def test_shipment_rows_are_readable(self, auth_client):
        upload_id = (await upload_csv(auth_client)).json()["upload"]["id"]
        response = await auth_client.get(f"/api/v1/uploads/{upload_id}/shipments")
        assert response.status_code == 200
        assert response.json()["total"] == 4

    async def test_deleting_an_upload_removes_it(self, auth_client):
        upload_id = (await upload_csv(auth_client)).json()["upload"]["id"]
        assert (await auth_client.delete(f"/api/v1/uploads/{upload_id}")).status_code == 200
        assert (await auth_client.get(f"/api/v1/uploads/{upload_id}")).status_code == 404

    async def test_latest_analysis_is_reachable_from_the_upload(self, auth_client):
        upload_id = (await upload_csv(auth_client)).json()["upload"]["id"]
        response = await auth_client.get(f"/api/v1/uploads/{upload_id}/analysis")
        assert response.status_code == 200
        assert response.json()["upload_id"] == upload_id

    async def test_latest_analysis_404s_for_another_users_upload(self, client):
        first = await client.post(
            "/api/v1/auth/register",
            json={"email": "owner2@example.com", "password": "sup3r-secret-pw"},
        )
        client.headers["Authorization"] = f"Bearer {first.json()['access_token']}"
        upload_id = (await upload_csv(client)).json()["upload"]["id"]

        second = await client.post(
            "/api/v1/auth/register",
            json={"email": "other2@example.com", "password": "sup3r-secret-pw"},
        )
        client.headers["Authorization"] = f"Bearer {second.json()['access_token']}"
        response = await client.get(f"/api/v1/uploads/{upload_id}/analysis")
        assert response.status_code == 404

    async def test_sample_csv_is_available_without_auth(self, client):
        response = await client.get("/api/v1/uploads/sample")
        assert response.status_code == 200
        assert "vendor" in response.json()["csv"]


class TestTenantIsolation:
    async def test_one_user_cannot_read_another_users_upload(self, client):
        # User A uploads.
        first = await client.post(
            "/api/v1/auth/register",
            json={"email": "a@example.com", "password": "sup3r-secret-pw"},
        )
        client.headers["Authorization"] = f"Bearer {first.json()['access_token']}"
        upload_id = (await upload_csv(client)).json()["upload"]["id"]

        # User B tries to read it.
        second = await client.post(
            "/api/v1/auth/register",
            json={"email": "b@example.com", "password": "sup3r-secret-pw"},
        )
        client.headers["Authorization"] = f"Bearer {second.json()['access_token']}"

        assert (await client.get(f"/api/v1/uploads/{upload_id}")).status_code == 404
        assert (await client.get(f"/api/v1/analytics/uploads/{upload_id}")).status_code == 404
        assert (await client.delete(f"/api/v1/uploads/{upload_id}")).status_code == 404


class TestAnalyticsEndpoints:
    """These must work without any AI call — that's the point of the split."""

    @pytest.fixture
    async def upload_id(self, auth_client) -> str:
        return (await upload_csv(auth_client)).json()["upload"]["id"]

    async def test_full_report(self, auth_client, upload_id):
        response = await auth_client.get(f"/api/v1/analytics/uploads/{upload_id}")
        assert response.status_code == 200

        body = response.json()
        assert body["kpis"]["total_shipments"] == 4
        assert body["kpis"]["late_shipments"] == 2
        assert body["kpis"]["late_shipment_pct"] == 50.0

    async def test_vendor_ranking(self, auth_client, upload_id):
        response = await auth_client.get(f"/api/v1/analytics/uploads/{upload_id}/vendors")
        vendors = response.json()
        assert vendors
        # GlobalParts is late on both of its shipments, so it must rank worst.
        assert vendors[0]["vendor"] == "GlobalParts"

    async def test_country_risk(self, auth_client, upload_id):
        response = await auth_client.get(f"/api/v1/analytics/uploads/{upload_id}/countries")
        assert response.status_code == 200
        assert {c["country"] for c in response.json()} >= {"China", "Brazil"}

    async def test_risk_breakdown_is_explainable(self, auth_client, upload_id):
        body = (await auth_client.get(f"/api/v1/analytics/uploads/{upload_id}/risk")).json()
        assert 0 <= body["score"] <= 100
        assert set(body["components"]) == set(body["weights"])

    async def test_trend_series(self, auth_client, upload_id):
        body = (await auth_client.get(f"/api/v1/analytics/uploads/{upload_id}/trend")).json()
        assert body["points"]
        assert body["direction"] in {
            "improving",
            "worsening",
            "stable",
            "insufficient_data",
        }

    async def test_history_is_empty_until_analyses_complete(self, auth_client, upload_id):
        body = (await auth_client.get("/api/v1/analytics/history")).json()
        assert body["direction"] == "insufficient_data"

    async def test_unknown_upload_is_404(self, auth_client):
        response = await auth_client.get(
            "/api/v1/analytics/uploads/00000000-0000-0000-0000-000000000000"
        )
        assert response.status_code == 404
