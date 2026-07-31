"""Tests for cache degradation and broker probing.

Both were written after running the app without Redis: the cache "degraded
gracefully" but cost ~4 seconds per call, and the Celery publish path blocked
the request for minutes instead of falling back.
"""

from __future__ import annotations

import socket

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.utils import cache
from app.workers import broker


class FakeRedis:
    """Redis double that can be told to fail."""

    def __init__(self, *, failing: bool = False) -> None:
        self.failing = failing
        self.store: dict[str, str] = {}
        self.calls = 0

    def _check(self) -> None:
        self.calls += 1
        if self.failing:
            raise RedisConnectionError("Error 22 connecting to localhost:6379")

    async def get(self, key: str) -> str | None:
        self._check()
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._check()
        self.store[key] = value

    async def delete(self, *keys: str) -> None:
        self._check()
        for key in keys:
            self.store.pop(key, None)

    async def ping(self) -> bool:
        self._check()
        return True


@pytest.fixture(autouse=True)
def _reset_state():
    cache.reset_circuit()
    broker.reset_probe_cache()
    yield
    cache.reset_circuit()
    broker.reset_probe_cache()


class TestCacheHappyPath:
    async def test_round_trips_a_value(self, monkeypatch):
        fake = FakeRedis()
        monkeypatch.setattr(cache, "get_redis", lambda: fake)

        await cache.cache_set("k", {"a": 1})
        assert await cache.cache_get("k") == {"a": 1}

    async def test_missing_key_returns_none(self, monkeypatch):
        monkeypatch.setattr(cache, "get_redis", lambda: FakeRedis())
        assert await cache.cache_get("absent") is None

    async def test_corrupt_entry_is_dropped_rather_than_raised(self, monkeypatch):
        fake = FakeRedis()
        fake.store["k"] = "not json"
        monkeypatch.setattr(cache, "get_redis", lambda: fake)

        assert await cache.cache_get("k") is None
        assert "k" not in fake.store


class TestCacheDegradation:
    async def test_a_redis_failure_returns_none_instead_of_raising(self, monkeypatch):
        monkeypatch.setattr(cache, "get_redis", lambda: FakeRedis(failing=True))
        assert await cache.cache_get("k") is None

    async def test_a_redis_failure_on_set_is_swallowed(self, monkeypatch):
        monkeypatch.setattr(cache, "get_redis", lambda: FakeRedis(failing=True))
        await cache.cache_set("k", {"a": 1})  # must not raise

    async def test_breaker_opens_and_stops_calling_redis(self, monkeypatch):
        fake = FakeRedis(failing=True)
        monkeypatch.setattr(cache, "get_redis", lambda: fake)

        for _ in range(cache.FAILURE_THRESHOLD):
            await cache.cache_get("k")
        calls_at_open = fake.calls

        # With the circuit open, further calls short-circuit instantly — this
        # is what removes seconds of latency per request during an outage.
        for _ in range(10):
            await cache.cache_get("k")
            await cache.cache_set("k", {"a": 1})

        assert fake.calls == calls_at_open

    async def test_breaker_closes_again_after_a_success(self, monkeypatch):
        fake = FakeRedis(failing=True)
        monkeypatch.setattr(cache, "get_redis", lambda: fake)

        await cache.cache_get("k")
        fake.failing = False
        await cache.cache_get("k")

        assert cache._consecutive_failures == 0

    async def test_ping_reports_false_while_the_breaker_is_open(self, monkeypatch):
        monkeypatch.setattr(cache, "get_redis", lambda: FakeRedis(failing=True))
        for _ in range(cache.FAILURE_THRESHOLD):
            await cache.ping()
        assert await cache.ping() is False

    async def test_unserialisable_payload_does_not_trip_the_breaker(self, monkeypatch):
        monkeypatch.setattr(cache, "get_redis", lambda: FakeRedis())
        await cache.cache_set("k", {"bad": object()})
        # A caller bug must not disable caching for everyone else.
        assert cache._consecutive_failures == 0


class TestBrokerProbe:
    def test_reports_unreachable_when_nothing_is_listening(self, monkeypatch):
        monkeypatch.setattr(broker.settings, "celery_broker_url", "redis://127.0.0.1:1/0")
        assert broker.broker_reachable(force=True) is False

    def test_reports_reachable_when_a_socket_accepts(self, monkeypatch):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]

            monkeypatch.setattr(broker.settings, "celery_broker_url", f"redis://127.0.0.1:{port}/0")
            assert broker.broker_reachable(force=True) is True

    def test_result_is_cached_between_calls(self, monkeypatch):
        monkeypatch.setattr(broker.settings, "celery_broker_url", "redis://127.0.0.1:1/0")
        probes = 0
        real_create_connection = socket.create_connection

        def counting_create_connection(*args, **kwargs):
            nonlocal probes
            probes += 1
            return real_create_connection(*args, **kwargs)

        monkeypatch.setattr(socket, "create_connection", counting_create_connection)

        broker.broker_reachable(force=True)
        for _ in range(5):
            broker.broker_reachable()

        # Probing on every upload would add latency for no benefit.
        assert probes == 1

    def test_non_tcp_transport_needs_no_probe(self, monkeypatch):
        monkeypatch.setattr(broker.settings, "celery_broker_url", "memory://")
        assert broker.broker_reachable(force=True) is True
