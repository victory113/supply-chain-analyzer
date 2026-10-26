"""Liveness, readiness, and metrics endpoints."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.api.deps import DbSession
from app.core import metrics
from app.core.config import settings
from app.utils import cache

router = APIRouter(tags=["health"])

_STARTED_AT = time.time()


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, Any]:
    """Cheap check: is the process up? Never touches a dependency."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - _STARTED_AT, 1),
    }


@router.get("/health/ready", summary="Readiness probe")
async def readiness(session: DbSession, response: Response) -> dict[str, Any]:
    """Deep check: can we actually serve traffic?

    Returns 503 when a hard dependency is down so orchestrators pull the
    instance out of rotation. Redis is *soft* — the cache degrades gracefully,
    so its absence is reported but doesn't fail readiness.
    """
    checks: dict[str, Any] = {}

    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"

    checks["redis"] = "ok" if await cache.ping() else "unavailable"
    checks["anthropic_configured"] = bool(settings.anthropic_api_key)

    ready = checks["database"] == "ok"
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"status": "ready" if ready else "not_ready", "checks": checks}


@router.get(
    "/metrics",
    summary="Prometheus scrape endpoint",
    include_in_schema=False,
    response_class=Response,
)
async def prometheus_metrics() -> Response:
    """Counters and histograms in Prometheus text format.

    Hidden from the OpenAPI schema: it is read by a scraper on a timer, not by
    a client, and its payload is a text exposition format rather than JSON.

    Unauthenticated, like the health probes, because a scraper runs alongside
    the service rather than logging in. The payload is deliberately aggregate
    only — counts and durations, never a user, dataset or filename — so there
    is nothing here worth protecting. In a cluster this port would be reachable
    only from inside it.
    """
    payload, content_type = metrics.render()
    return Response(content=payload, media_type=content_type)
