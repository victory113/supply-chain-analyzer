"""API tests for registration, login, and token-protected routes."""

from __future__ import annotations

VALID_USER = {
    "email": "new.user@example.com",
    "password": "sup3r-secret-pw",
    "full_name": "New User",
}


class TestRegistration:
    async def test_register_returns_a_token_and_the_user(self, client):
        response = await client.post("/api/v1/auth/register", json=VALID_USER)
        assert response.status_code == 201
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["user"]["email"] == VALID_USER["email"]
        assert "password" not in body["user"]

    async def test_duplicate_email_conflicts(self, client):
        await client.post("/api/v1/auth/register", json=VALID_USER)
        response = await client.post("/api/v1/auth/register", json=VALID_USER)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "conflict"

    async def test_email_is_normalised_so_case_does_not_create_a_second_account(self, client):
        await client.post("/api/v1/auth/register", json=VALID_USER)
        response = await client.post(
            "/api/v1/auth/register",
            json={**VALID_USER, "email": "New.User@EXAMPLE.com"},
        )
        assert response.status_code == 409

    async def test_short_password_is_rejected(self, client):
        response = await client.post(
            "/api/v1/auth/register", json={**VALID_USER, "password": "short"}
        )
        assert response.status_code == 422

    async def test_all_letters_password_is_rejected(self, client):
        response = await client.post(
            "/api/v1/auth/register", json={**VALID_USER, "password": "onlyletters"}
        )
        assert response.status_code == 422

    async def test_malformed_email_is_rejected(self, client):
        response = await client.post(
            "/api/v1/auth/register", json={**VALID_USER, "email": "not-an-email"}
        )
        assert response.status_code == 422


class TestLogin:
    async def test_correct_credentials_return_a_token(self, client):
        await client.post("/api/v1/auth/register", json=VALID_USER)
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": VALID_USER["email"], "password": VALID_USER["password"]},
        )
        assert response.status_code == 200
        assert response.json()["access_token"]

    async def test_wrong_password_is_rejected(self, client):
        await client.post("/api/v1/auth/register", json=VALID_USER)
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": VALID_USER["email"], "password": "wrong-password"},
        )
        assert response.status_code == 401

    async def test_unknown_email_gives_the_same_error_as_a_wrong_password(self, client):
        # Identical wording either way — the response must not confirm whether
        # an address is registered.
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "sup3r-secret-pw"},
        )
        assert response.status_code == 401
        assert response.json()["error"]["message"] == "Incorrect email or password."


class TestProtectedRoutes:
    async def test_me_returns_the_authenticated_user(self, auth_client):
        response = await auth_client.get("/api/v1/auth/me")
        assert response.status_code == 200
        assert response.json()["email"] == "analyst@example.com"

    async def test_missing_token_is_rejected(self, client):
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401

    async def test_garbage_token_is_rejected(self, client):
        client.headers["Authorization"] = "Bearer not.a.real.token"
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401


class TestHealth:
    async def test_liveness_is_open_and_cheap(self, client):
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    async def test_readiness_reports_dependency_checks(self, client):
        response = await client.get("/api/v1/health/ready")
        body = response.json()
        assert "database" in body["checks"]
        assert "redis" in body["checks"]

    async def test_every_response_carries_a_request_id(self, client):
        response = await client.get("/api/v1/health")
        assert response.headers.get("X-Request-ID")
