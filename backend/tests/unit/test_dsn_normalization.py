"""Tests for managed-provider DSN normalization.

Neon, Render and Heroku hand out libpq-style connection strings. Pasting one
into DATABASE_URL unchanged fails at first connect, not at startup, which makes
it a miserable thing to debug on a fresh deploy. These pin the fixes.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings


def dsn(url: str) -> str:
    return str(Settings(database_url=url).database_url)


class TestDriverPrefix:
    def test_bare_postgresql_gets_the_asyncpg_driver(self):
        assert dsn("postgresql://u:p@host/db").startswith("postgresql+asyncpg://")

    def test_heroku_style_postgres_scheme_is_upgraded(self):
        # SQLAlchemy rejects `postgres://` outright.
        assert dsn("postgres://u:p@host/db").startswith("postgresql+asyncpg://")

    def test_an_explicit_driver_is_left_alone(self):
        url = "postgresql+asyncpg://u:p@host/db"
        assert dsn(url) == url

    def test_sqlite_is_untouched(self):
        assert dsn("sqlite+aiosqlite:///./dev.db") == "sqlite+aiosqlite:///./dev.db"


class TestSslParameters:
    def test_sslmode_becomes_ssl(self):
        # asyncpg raises TypeError on `sslmode`; its parameter is `ssl`.
        assert dsn("postgresql://u:p@host/db?sslmode=require") == (
            "postgresql+asyncpg://u:p@host/db?ssl=require"
        )

    def test_channel_binding_is_dropped(self):
        # Neon includes it; asyncpg has no such parameter.
        result = dsn("postgresql://u:p@host/db?sslmode=require&channel_binding=require")
        assert "channel_binding" not in result
        assert "ssl=require" in result

    def test_a_neon_style_url_ends_up_connectable(self):
        result = dsn(
            "postgresql://user:pw@ep-cool-name-123.us-east-2.aws.neon.tech/neondb"
            "?sslmode=require&channel_binding=require"
        )
        assert result == (
            "postgresql+asyncpg://user:pw@ep-cool-name-123.us-east-2.aws.neon.tech"
            "/neondb?ssl=require"
        )

    def test_no_dangling_separator_when_the_only_param_is_removed(self):
        result = dsn("postgresql://u:p@host/db?channel_binding=require")
        assert not result.endswith("?")
        assert not result.endswith("&")

    def test_other_parameters_survive(self):
        result = dsn("postgresql://u:p@host/db?sslmode=require&application_name=sca")
        assert "application_name=sca" in result


class TestIsSqliteStillWorks:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("sqlite+aiosqlite:///./dev.db", True),
            ("postgresql://u:p@host/db", False),
            ("postgres://u:p@host/db", False),
        ],
    )
    def test_detection_survives_normalization(self, url: str, expected: bool):
        assert Settings(database_url=url).is_sqlite is expected
