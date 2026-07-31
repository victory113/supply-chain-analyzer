"""Chat schemas for the retrieval-grounded Q&A endpoint."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    # Scope the retrieval. Omit to query across the user's whole history.
    upload_id: uuid.UUID | None = None
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


class ChatSource(BaseModel):
    """What the answer was grounded in — makes the response auditable."""

    kind: str = Field(description="kpi | vendor | country | trend | analysis")
    reference: str
    detail: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[ChatSource]
    uploads_considered: int
