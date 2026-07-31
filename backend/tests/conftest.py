"""Shared test fixtures.

Environment variables are set *before* any app import so the cached settings
singleton picks up the test configuration. Tests run against in-memory SQLite:
the GUID/JSON column variants in ``app.db.base`` make the same models work on
both SQLite and Postgres, which keeps the suite fast and dependency-free while
CI still exercises Postgres via the compose stack.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from datetime import date

os.environ.update(
    ENVIRONMENT="test",
    DATABASE_URL="sqlite+aiosqlite:///:memory:",
    REDIS_URL="redis://localhost:6379/15",
    SECRET_KEY="test-secret-key-not-used-anywhere-real",
    ANTHROPIC_API_KEY="test-key",
    LOG_LEVEL="WARNING",
)

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models.enums import ShipmentStatus
from app.models.shipment import Shipment
from app.schemas.analysis import LLMAnalysisPayload, LLMRiskItem
from app.services.analytics import ShipmentFact
from app.services.claude import LLMResult


@pytest.fixture
async def engine():
    """One in-memory database per test, shared across connections."""
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    async with factory() as sess:
        yield sess


@pytest.fixture
async def client(engine, monkeypatch) -> AsyncGenerator[AsyncClient, None]:
    """App client wired to the test database, with the job queue stubbed out."""
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as sess:
            yield sess

    # Never enqueue (or inline-run) a real analysis from an API test — that
    # would reach for a broker and then for Anthropic.
    import app.api.v1.uploads as uploads_module

    monkeypatch.setattr(
        uploads_module, "_enqueue_analysis", lambda analysis_id, background: "test-task"
    )

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def auth_client(client: AsyncClient) -> AsyncClient:
    """A client with a registered user's bearer token already attached."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "analyst@example.com",
            "password": "sup3r-secret-pw",
            "full_name": "Test Analyst",
        },
    )
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


class FakeClaudeService:
    """Deterministic stand-in for the Anthropic client.

    Records the prompts it was given so tests can assert on grounding without
    a network call.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def analyze(self, report):
        from app.services.prompts import build_analysis_prompt

        self.calls.append(build_analysis_prompt(report))
        return LLMResult(
            payload=LLMAnalysisPayload(
                summary="Delays are concentrated in a small number of vendors.",
                risks=[
                    LLMRiskItem(
                        title="Vendor concentration",
                        risk_level="HIGH",
                        explanation="One vendor carries most of the late volume.",
                        recommendation="Qualify a second supplier this quarter.",
                        affected_items=["GlobalParts Co"],
                        evidence_metric="vendors[0].health_score",
                    )
                ],
                healthy_signals=["Most shipments arrived on time."],
            ),
            model="claude-opus-5",
            input_tokens=1200,
            output_tokens=300,
            duration_ms=850,
        )

    async def compare(self, before, after):
        from app.services.claude import LLMComparisonPayload

        return LLMResult(
            payload=LLMComparisonPayload(
                net_change="WORSENED",
                summary="Delays increased across the board.",
                changes=[],
            ),
            model="claude-opus-5",
            input_tokens=900,
            output_tokens=200,
            duration_ms=700,
        )

    async def answer_question(self, question, context, *, uploads_considered, history=None):
        self.calls.append(context)
        return LLMResult(
            payload=f"Based on the data: {question}",
            model="claude-opus-5",
            input_tokens=500,
            output_tokens=120,
            duration_ms=400,
        )


@pytest.fixture
def fake_claude() -> FakeClaudeService:
    return FakeClaudeService()


def make_fact(
    *,
    vendor: str = "Acme",
    country: str = "China",
    delay: int = 0,
    lead_time: int | None = 10,
    quantity: int = 100,
    unit_cost: float = 10.0,
    status: ShipmentStatus | None = None,
    occurred_on: date | None = None,
) -> ShipmentFact:
    """Build a ShipmentFact with sensible defaults, overriding only what matters."""
    if status is None:
        status = ShipmentStatus.DELAYED if delay > 0 else ShipmentStatus.ON_TIME
    return ShipmentFact(
        vendor=vendor,
        origin_country=country,
        destination="Dallas TX",
        product="Widget",
        quantity=quantity,
        unit_cost=unit_cost,
        lead_time_days=lead_time,
        delay_days=delay,
        status=status,
        occurred_on=occurred_on,
    )


def make_shipment(upload_id: uuid.UUID, **kwargs) -> Shipment:
    defaults = {
        "shipment_ref": "S001",
        "vendor": "Acme",
        "product": "Widget",
        "origin_country": "China",
        "destination": "Dallas TX",
        "quantity": 100,
        "unit_cost": 10.0,
        "lead_time_days": 10,
        "delay_days": 0,
        "status": ShipmentStatus.ON_TIME,
    }
    defaults.update(kwargs)
    return Shipment(upload_id=upload_id, **defaults)
