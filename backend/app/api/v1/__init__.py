"""v1 API router aggregation."""

from fastapi import APIRouter

from app.api.v1 import analyses, analytics, auth, chat, uploads

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(uploads.router)
api_router.include_router(analyses.router)
api_router.include_router(analytics.router)
api_router.include_router(chat.router)

__all__ = ["api_router"]
