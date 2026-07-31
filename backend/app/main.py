"""FastAPI application factory and entry point."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.api.v1.health import router as health_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.db.init_db import create_schema_for_local_dev
from app.db.session import engine
from app.middleware import RequestContextMiddleware
from app.utils.cache import close_redis

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    logger.info(
        "startup",
        app=settings.app_name,
        environment=settings.environment,
        model=settings.anthropic_model,
    )
    if settings.is_production and settings.secret_key.startswith("dev-only"):
        # Fail loudly rather than serving forgeable tokens in production.
        raise RuntimeError("SECRET_KEY must be set to a real value in production.")

    # No-op on Postgres, where Alembic owns the schema.
    if await create_schema_for_local_dev(engine):
        logger.info("local_dev_mode", database="sqlite", migrations="skipped")

    yield

    await close_redis()
    await engine.dispose()
    logger.info("shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="2.0.0",
        description=(
            "AI supply chain intelligence platform. Metrics are computed "
            "deterministically in Python; Claude explains them."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Response-Time-ms"],
    )
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)

    app.include_router(health_router, prefix=settings.api_v1_prefix)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "service": settings.app_name,
            "version": "2.0.0",
            "docs": "/docs",
            "health": f"{settings.api_v1_prefix}/health",
        }

    return app


app = create_app()
