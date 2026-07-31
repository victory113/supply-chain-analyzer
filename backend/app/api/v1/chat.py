"""Chat route: ask questions about your own stored supply chain data."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse, summary="Ask about your data")
async def ask(payload: ChatRequest, session: DbSession, current_user: CurrentUser) -> ChatResponse:
    """Answers are grounded in retrieved metrics and cite their sources.

    Scope with ``upload_id`` for a single dataset, or omit it to reason across
    the user's recent history.
    """
    return await ChatService(session).ask(payload, current_user.id)
