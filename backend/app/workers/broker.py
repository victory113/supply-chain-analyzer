"""Broker reachability probe.

Celery cannot be made to fail fast on publish: ``retry=False`` on
``apply_async`` disables *publish* retry, but kombu still runs its own
connection-establishment loop (``broker_connection_max_retries``, default 100),
which blocks the request for minutes when the broker is down. Turning that off
globally would also stop a running worker from reconnecting, which we do want.

So the API probes the socket itself before publishing, and falls back to an
in-process task when nothing is listening.
"""

from __future__ import annotations

import socket
import time
from urllib.parse import urlparse

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

PROBE_TIMEOUT_SECONDS = 0.5
# Re-probing on every upload would add latency for no benefit; a broker that
# just came up will be picked up within this window.
CACHE_TTL_SECONDS = 5.0

_cached_result: bool | None = None
_cached_at = 0.0


def _broker_address() -> tuple[str, int] | None:
    """Extract host and port from the broker URL, if it is a TCP transport."""
    parsed = urlparse(settings.broker_url)
    if parsed.scheme.startswith("redis") or parsed.scheme in {"amqp", "amqps"}:
        default_port = 6379 if parsed.scheme.startswith("redis") else 5672
        return parsed.hostname or "localhost", parsed.port or default_port
    # memory:// and other in-process transports need no probe.
    return None


def broker_reachable(*, force: bool = False) -> bool:
    """True when the broker accepts a TCP connection.

    Result is cached for a few seconds. A non-TCP transport always reports
    reachable, since there is no socket to test.
    """
    global _cached_result, _cached_at

    now = time.monotonic()
    if not force and _cached_result is not None and now - _cached_at < CACHE_TTL_SECONDS:
        return _cached_result

    address = _broker_address()
    if address is None:
        _cached_result, _cached_at = True, now
        return True

    host, port = address
    try:
        with socket.create_connection((host, port), timeout=PROBE_TIMEOUT_SECONDS):
            reachable = True
    except OSError:
        reachable = False

    if reachable != _cached_result:
        logger.info("broker_probe", host=host, port=port, reachable=reachable)

    _cached_result, _cached_at = reachable, now
    return reachable


def reset_probe_cache() -> None:
    """Clear the cached probe result (used by tests)."""
    global _cached_result, _cached_at
    _cached_result, _cached_at = None, 0.0
