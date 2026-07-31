"""Tests for the local-dev schema bootstrap.

The guard rails matter more than the happy path here: this code must never run
against a migration-managed database.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.db.init_db import UnsafeSchemaBootstrapError, create_schema_for_local_dev


class TestIsSqlite:
    def test_detects_a_sqlite_dsn(self, monkeypatch):
        monkeypatch.setattr(settings, "database_url", "sqlite+aiosqlite:///./dev.db")
        assert settings.is_sqlite is True

    def test_detects_a_postgres_dsn(self, monkeypatch):
        monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://u:p@localhost:5432/db")
        assert settings.is_sqlite is False


class TestSchemaBootstrap:
    async def test_creates_every_table_on_sqlite(self, monkeypatch, tmp_path):
        monkeypatch.setattr(settings, "database_url", "sqlite+aiosqlite:///:memory:")
        monkeypatch.setattr(settings, "environment", "local")

        db_path = tmp_path / "dev.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        try:
            assert await create_schema_for_local_dev(engine) is True

            async with engine.connect() as connection:
                tables = await connection.run_sync(
                    lambda sync_conn: set(inspect(sync_conn).get_table_names())
                )
        finally:
            await engine.dispose()

        assert {"users", "uploads", "shipments", "analyses", "risks"} <= tables

    async def test_is_idempotent(self, monkeypatch, tmp_path):
        monkeypatch.setattr(settings, "database_url", "sqlite+aiosqlite:///:memory:")
        monkeypatch.setattr(settings, "environment", "local")

        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'dev.db'}")
        try:
            # Startup runs this every time; a second call must not raise.
            assert await create_schema_for_local_dev(engine) is True
            assert await create_schema_for_local_dev(engine) is True
        finally:
            await engine.dispose()

    async def test_skips_a_postgres_dsn_instead_of_bypassing_alembic(self, monkeypatch, engine):
        monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://u:p@localhost:5432/db")
        assert await create_schema_for_local_dev(engine) is False

    async def test_refuses_to_run_in_production(self, monkeypatch, engine):
        monkeypatch.setattr(settings, "database_url", "sqlite+aiosqlite:///./prod.db")
        monkeypatch.setattr(settings, "environment", "production")

        with pytest.raises(UnsafeSchemaBootstrapError, match="alembic upgrade head"):
            await create_schema_for_local_dev(engine)
