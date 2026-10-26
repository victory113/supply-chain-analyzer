"""Request-scoped middleware: correlation IDs, access logs, timing."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core import metrics
from app.core.logging import get_logger

logger = get_logger("api.access")

REQUEST_ID_HEADER = "X-Request-ID"


def _route_of(request: Request) -> str:
    """The matched route *template*, never the raw path.

    Prometheus keeps one time series per distinct label combination, so
    labelling by `request.url.path` would mint a new series for every upload
    ID anyone has ever fetched. The template collapses all of those into
    ``/api/v1/uploads/{upload_id}``. Requests that matched nothing share a
    single bucket for the same reason — a 404 scanner must not be able to
    create unbounded series.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attaches a request ID to every log line emitted during the request.

    Trusts an inbound ``X-Request-ID`` so a trace survives across services, and
    echoes it back so clients can quote it in a bug report.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # The exception handler builds the response; log the timing here so
            # failed requests still appear in the access log.
            elapsed = time.perf_counter() - started
            logger.exception("request_failed", duration_ms=round(elapsed * 1000, 2))
            metrics.observe_request(request.method, _route_of(request), 500, elapsed)
            raise

        elapsed = time.perf_counter() - started
        metrics.observe_request(request.method, _route_of(request), response.status_code, elapsed)
        duration_ms = round(elapsed * 1000, 2)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers["X-Response-Time-ms"] = str(duration_ms)

        # Health checks fire constantly; logging them buries real traffic.
        if not request.url.path.startswith("/api/v1/health"):
            logger.info(
                "request_completed",
                status_code=response.status_code,
                duration_ms=duration_ms,
            )

        return response
