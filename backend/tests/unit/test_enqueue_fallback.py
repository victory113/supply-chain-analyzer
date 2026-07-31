"""Regression tests for the analysis enqueue fallback.

Running the app without Redis exposed a hang here: `.delay()` inherits Celery's
default publish-retry policy and blocks for ~20 attempts with backoff when the
broker is unreachable, so the "fall back to an in-process task" branch was
never reached in any useful time. These tests pin both halves of the fix.
"""

from __future__ import annotations

import uuid

import pytest

from app.api.v1.uploads import _enqueue_analysis
from app.workers.celery_app import celery_app


class FakeBackgroundTasks:
    """Stand-in for FastAPI's BackgroundTasks."""

    def __init__(self) -> None:
        self.tasks: list[tuple[object, tuple[object, ...]]] = []

    def add_task(self, func, *args) -> None:
        self.tasks.append((func, args))


class TestEnqueue:
    def test_publishes_without_retrying_when_the_broker_is_up(self, monkeypatch):
        monkeypatch.setattr("app.workers.broker.broker_reachable", lambda: True)
        captured: dict[str, object] = {}

        class FakeResult:
            id = "task-123"

        def fake_apply_async(*, args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return FakeResult()

        monkeypatch.setattr("app.workers.tasks.run_analysis_task.apply_async", fake_apply_async)

        analysis_id = uuid.uuid4()
        background = FakeBackgroundTasks()
        task_id = _enqueue_analysis(analysis_id, background)

        assert task_id == "task-123"
        assert captured["args"] == [str(analysis_id)]
        # Without this the request hangs instead of falling back.
        assert captured["kwargs"]["retry"] is False
        assert background.tasks == []

    def test_skips_publishing_entirely_when_the_broker_is_unreachable(self, monkeypatch):
        monkeypatch.setattr("app.workers.broker.broker_reachable", lambda: False)

        def must_not_be_called(**_kwargs):
            raise AssertionError("apply_async must not run when the probe fails")

        monkeypatch.setattr("app.workers.tasks.run_analysis_task.apply_async", must_not_be_called)

        background = FakeBackgroundTasks()
        assert _enqueue_analysis(uuid.uuid4(), background) is None
        assert len(background.tasks) == 1

    def test_falls_back_to_an_inline_task_when_publishing_fails(self, monkeypatch):
        # The narrow race: probe succeeds, broker dies before publish.
        monkeypatch.setattr("app.workers.broker.broker_reachable", lambda: True)

        def boom(**_kwargs):
            raise ConnectionError("Error 22 connecting to localhost:6379")

        monkeypatch.setattr("app.workers.tasks.run_analysis_task.apply_async", boom)

        analysis_id = uuid.uuid4()
        background = FakeBackgroundTasks()
        task_id = _enqueue_analysis(analysis_id, background)

        # No Celery task id, but the work is still scheduled in-process so the
        # upload is not silently dropped.
        assert task_id is None
        assert len(background.tasks) == 1
        assert background.tasks[0][1] == (str(analysis_id),)

    @pytest.mark.parametrize("option", ["socket_connect_timeout", "socket_timeout"])
    def test_broker_transport_bounds_the_connect(self, option):
        # An unreachable broker must surface in seconds, not on the OS default.
        assert celery_app.conf.broker_transport_options[option] <= 5
