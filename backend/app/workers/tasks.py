"""Background tasks."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from celery import Task
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.logging import get_logger
from app.db.session import build_engine
from app.services.analysis import AnalysisService
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


def run_async(coro_factory: Any) -> Any:
    """Run an async unit of work in a fresh event loop with its own engine.

    asyncpg connections are bound to the event loop that created them, so the
    module-level engine from the API process cannot be reused here. Building
    (and disposing) a per-task engine costs one connection setup and avoids a
    class of "attached to a different loop" failures that only appear under
    concurrency.
    """

    async def _runner() -> Any:
        engine = build_engine()
        factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
        try:
            async with factory() as session:
                return await coro_factory(session)
        finally:
            await engine.dispose()

    return asyncio.run(_runner())


@celery_app.task(
    bind=True,
    name="analysis.run",
    max_retries=2,
    default_retry_delay=30,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
)
def run_analysis_task(self: Task, analysis_id: str) -> dict[str, str]:
    """Compute analytics and generate the AI narrative for one analysis.

    ``AnalysisService.run_analysis`` records its own failures on the row, so a
    model error resolves to a terminal FAILED state the frontend can poll —
    only infrastructure errors bubble up to Celery's retry.
    """
    logger.info("task_started", task="analysis.run", analysis_id=analysis_id)

    async def _work(session: Any) -> dict[str, str]:
        service = AnalysisService(session)
        analysis = await service.run_analysis(uuid.UUID(analysis_id))
        return {"analysis_id": str(analysis.id), "status": str(analysis.status)}

    try:
        result: dict[str, str] = run_async(_work)
    except Exception as exc:
        logger.exception("task_failed", task="analysis.run", analysis_id=analysis_id)
        raise self.retry(exc=exc) from exc

    logger.info("task_finished", task="analysis.run", **result)
    return result


@celery_app.task(name="analysis.warm_history")
def warm_history_task(user_id: str) -> dict[str, str]:
    """Pre-compute a user's cross-upload history so the dashboard loads warm."""

    async def _work(session: Any) -> dict[str, str]:
        report = await AnalysisService(session).build_history(uuid.UUID(user_id))
        return {"user_id": user_id, "points": str(len(report.points))}

    return run_async(_work)  # type: ignore[no-any-return]
