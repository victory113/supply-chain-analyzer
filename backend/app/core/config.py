"""Application settings, loaded once from the environment."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── App ────────────────────────────────────────────────────────────
    app_name: str = "Supply Chain Intelligence API"
    environment: Literal["local", "test", "staging", "production"] = "local"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    log_json: bool = False

    # ── Security ───────────────────────────────────────────────────────
    secret_key: str = Field(
        default="dev-only-insecure-key-change-me",
        description="HMAC key for signing JWTs. Must be overridden outside local dev.",
    )
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60 * 12
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"]
    )

    # ── Database ───────────────────────────────────────────────────────
    database_url: PostgresDsn | str = "postgresql+asyncpg://sca:sca@localhost:5432/sca"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # ── Redis / Celery ─────────────────────────────────────────────────
    redis_url: RedisDsn | str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    cache_ttl_seconds: int = 60 * 15

    # ── Anthropic ──────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"
    anthropic_max_tokens: int = 4000
    anthropic_timeout_seconds: float = 120.0

    # ── Ingestion limits ───────────────────────────────────────────────
    max_upload_bytes: int = 10 * 1024 * 1024  # 10 MB
    max_rows_per_upload: int = 50_000
    max_rows_in_prompt: int = 200

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated string so the value survives a .env round-trip."""
        if isinstance(value, str) and not value.startswith("["):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or str(self.redis_url)

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or str(self.redis_url)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_sqlite(self) -> bool:
        """True when pointed at SQLite — the zero-dependency local dev mode.

        Postgres is what production runs; SQLite exists so the app can be run
        end-to-end with nothing but Python installed. The two are kept honest
        by the GUID/JSON column variants in ``app.db.base``.
        """
        return str(self.database_url).startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    """Cached accessor so settings are parsed once per process."""
    return Settings()


settings = get_settings()
