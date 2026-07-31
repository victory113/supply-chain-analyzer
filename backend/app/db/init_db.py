"""Schema bootstrap for the zero-dependency local dev mode.

Postgres schemas are owned by Alembic — always. This module exists only so the
app can run against SQLite with nothing else installed, and it refuses to touch
any other database rather than quietly bypassing migrations.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import settings
from app.core.logging import get_logger
from app.models import Base

logger = get_logger(__name__)


class UnsafeSchemaBootstrapError(RuntimeError):
    """Raised when create_all is attempted against a migration-managed database."""


async def create_schema_for_local_dev(engine: AsyncEngine) -> bool:
    """Create any missing tables when running on SQLite.

    Returns True if the bootstrap ran, False if it was skipped because the app
    is pointed at a real database.

    ``create_all`` is a no-op for tables that already exist, so this is safe to
    call on every startup — but it does *not* alter existing tables, which is
    exactly why Postgres must go through Alembic instead.
    """
    if not settings.is_sqlite:
        logger.debug("schema_bootstrap_skipped", reason="not_sqlite")
        return False

    if settings.is_production:
        # Belt and braces: even a misconfigured SQLite DSN shouldn't get a
        # migration-free schema in production.
        raise UnsafeSchemaBootstrapError(
            "Refusing to create tables directly in production. Run 'alembic upgrade head'."
        )

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    logger.info(
        "schema_bootstrap_complete",
        tables=len(Base.metadata.tables),
        dsn_kind="sqlite",
    )
    return True
