"""Async engine, session factory, and the FastAPI session dependency."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


def build_engine(url: str | None = None) -> AsyncEngine:
    """Create an engine.

    Celery workers call this to build a *fresh* engine inside each task's event
    loop — asyncpg connections are bound to the loop that created them, so a
    module-level engine cannot be shared with `asyncio.run()`.
    """
    dsn = url or str(settings.database_url)
    kwargs: dict = {"echo": settings.db_echo, "pool_pre_ping": True}
    if not dsn.startswith("sqlite"):
        kwargs["pool_size"] = settings.db_pool_size
        kwargs["max_overflow"] = settings.db_max_overflow
    return create_async_engine(dsn, **kwargs)


engine: AsyncEngine = build_engine()

SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine, expire_on_commit=False, autoflush=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one session per request, rolled back on failure."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession] | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """Session context manager for code outside the request cycle (workers, CLI)."""
    maker = factory or SessionLocal
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
