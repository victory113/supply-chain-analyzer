"""Redis cache helper with a circuit breaker.

Cache misses and Redis outages must never fail a request — every operation
degrades to "no cache" and logs. The cache holds derived data only, so a stale
or absent entry costs latency, not correctness.

The circuit breaker exists because "degrades gracefully" is not the same as
"degrades cheaply": redis-py retries a refused connection internally, so with
Redis down each call cost seconds, and a page issuing a get and a set paid it
twice. After a few consecutive failures the breaker opens and calls return
instantly until the cooldown expires.
"""

from __future__ import annotations

import json
import time
from typing import Any

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Fail fast: a healthy local Redis answers in single-digit milliseconds, so a
# half-second ceiling only ever trips on a real problem.
SOCKET_TIMEOUT_SECONDS = 0.5
FAILURE_THRESHOLD = 3
COOLDOWN_SECONDS = 30.0

_client: aioredis.Redis | None = None
_consecutive_failures = 0
_circuit_open_until = 0.0


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(
            str(settings.redis_url),
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=SOCKET_TIMEOUT_SECONDS,
            socket_timeout=SOCKET_TIMEOUT_SECONDS,
            retry_on_timeout=False,
        )
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# ── Circuit breaker ───────────────────────────────────────────────────


def _circuit_is_open() -> bool:
    return time.monotonic() < _circuit_open_until


def _record_failure(operation: str, error: Exception) -> None:
    global _consecutive_failures, _circuit_open_until
    _consecutive_failures += 1
    if _consecutive_failures >= FAILURE_THRESHOLD and not _circuit_is_open():
        _circuit_open_until = time.monotonic() + COOLDOWN_SECONDS
        logger.warning(
            "cache_circuit_opened",
            failures=_consecutive_failures,
            cooldown_seconds=COOLDOWN_SECONDS,
            error=str(error),
        )
    else:
        logger.warning("cache_unavailable", op=operation, error=str(error))


def _record_success() -> None:
    global _consecutive_failures, _circuit_open_until
    if _consecutive_failures or _circuit_open_until:
        logger.info("cache_recovered")
    _consecutive_failures = 0
    _circuit_open_until = 0.0


def reset_circuit() -> None:
    """Clear breaker state (used by tests and after a config change)."""
    global _consecutive_failures, _circuit_open_until
    _consecutive_failures = 0
    _circuit_open_until = 0.0


# ── Keys ──────────────────────────────────────────────────────────────


def analytics_key(upload_id: str) -> str:
    return f"analytics:v1:{upload_id}"


def history_key(user_id: str) -> str:
    return f"history:v1:{user_id}"


# ── Operations ────────────────────────────────────────────────────────


async def cache_get(key: str) -> dict[str, Any] | None:
    if _circuit_is_open():
        return None

    try:
        raw = await get_redis().get(key)
    except (RedisError, OSError) as exc:
        _record_failure("get", exc)
        return None

    _record_success()
    if raw is None:
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # A poisoned entry (format change, partial write) shouldn't wedge the
        # endpoint — drop it and recompute.
        logger.warning("cache_corrupt", key=key)
        await cache_delete(key)
        return None


async def cache_set(key: str, value: dict[str, Any], *, ttl: int | None = None) -> None:
    if _circuit_is_open():
        return

    try:
        await get_redis().set(
            key, json.dumps(value, default=str), ex=ttl or settings.cache_ttl_seconds
        )
    except (RedisError, OSError) as exc:
        _record_failure("set", exc)
        return
    except TypeError as exc:
        # Unserialisable payload is a bug in the caller, not a Redis outage —
        # don't let it trip the breaker.
        logger.error("cache_serialization_failed", key=key, error=str(exc))
        return

    _record_success()


async def cache_delete(*keys: str) -> None:
    if not keys or _circuit_is_open():
        return
    try:
        await get_redis().delete(*keys)
    except (RedisError, OSError) as exc:
        _record_failure("delete", exc)
        return
    _record_success()


async def ping() -> bool:
    """Used by the health endpoint. Reports through the breaker."""
    if _circuit_is_open():
        return False
    try:
        result = bool(await get_redis().ping())
    except (RedisError, OSError) as exc:
        _record_failure("ping", exc)
        return False
    _record_success()
    return result
