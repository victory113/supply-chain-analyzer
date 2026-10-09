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

    kind: str = Field(description="kpi | vendor | country | trend | dimension | ...")
    reference: str
    detail: str


class ChatToolCall(BaseModel):
    """One tool the model chose to call, in order.

    Returned to the client so a user can see *why* an answer says what it
    says. With the model choosing its own retrieval, showing the trace is the
    only way the user can tell a well-grounded answer from a lucky one.
    """

    name: str
    arguments: dict[str, str] = Field(default_factory=dict)
    ok: bool = True
    summary: str = ""


class ChatResponse(BaseModel):
    answer: str
    sources: list[ChatSource]
    uploads_considered: int
    tool_calls: list[ChatToolCall] = Field(default_factory=list)
