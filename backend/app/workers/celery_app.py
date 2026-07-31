"""Celery application.

Celery workers are synchronous processes, but the whole data layer is async.
Rather than maintaining a parallel sync stack, each task drives the existing
async code with ``asyncio.run`` — see ``run_async`` in tasks.py for why the
engine has to be rebuilt inside that loop.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import settings
from app.core.logging import configure_logging

configure_logging()

celery_app = Celery(
    "supply_chain_analyzer",
    broker=settings.broker_url,
    backend=settings.result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Only ack after the task finishes, so a worker crash re-queues the job
    # rather than silently dropping an analysis.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # A single analysis is one Claude call; well under these ceilings.
    task_soft_time_limit=300,
    task_time_limit=360,
    result_expires=60 * 60 * 24,
    # Workers should wait for a broker that isn't up yet; API processes
    # publishing a task should not (they pass retry=False per call).
    broker_connection_retry_on_startup=True,
    # Bound the TCP connect so an unreachable broker surfaces in seconds
    # rather than hanging on the OS default timeout.
    broker_transport_options={"socket_connect_timeout": 3, "socket_timeout": 3},
    task_default_queue="analysis",
)
