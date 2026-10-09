"""Tool-using agent for questions about the user's stored supply chain data.

This used to be a keyword router: the server scanned the question for words
like "vendor" or "trend", decided which metric families to retrieve, pasted
them all into one prompt, and asked for an answer. That works for questions
whose shape you anticipated, and fails quietly for everything else — a
question about carriers retrieved vendor data because "who" was in the
keyword list, and nothing reported that the wrong thing had been fetched.

Now the model is given tools and decides for itself. "Which carrier is worst,
and is that getting better?" becomes a carrier lookup followed by a trend
lookup, chosen by the model, in that order, because the second question
depends on the answer to the first. That is the difference between retrieval
and an agent: not that the model is cleverer, but that the *sequence* is no
longer fixed in advance by us.

What did not change is the grounding boundary. Tools return metrics computed
in Python; the model still never calculates a figure of its own.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.repositories.upload import UploadRepository
from app.schemas.chat import ChatRequest, ChatResponse, ChatSource, ChatToolCall
from app.services.agent_tools import AgentToolset
from app.services.claude import ClaudeService

logger = get_logger(__name__)

# Enough for "look it up, then look up the thing that depends on it, then
# answer" with room to recover from one bad dataset name. Higher mostly buys
# latency: each step is a full round trip to the model.
MAX_AGENT_STEPS = 6

AGENT_SYSTEM_PROMPT = """You are a supply chain analyst answering questions about \
the user's own uploaded shipment data.

You cannot see the data directly. Use the provided tools to retrieve it, then answer \
from what they return.

Rules:
1. Never state a figure that did not come back from a tool. You have no other source \
for numbers, and you must not estimate, extrapolate or recall one.
2. Call as many tools as the question needs, including several in sequence when a \
later lookup depends on an earlier answer. Do not call tools you do not need.
3. If a tool reports that a dataset has no data for something, say that plainly. \
Absent data is not zero, and "the file didn't include carrier information" is a \
correct and useful answer.
4. If a tool returns an error, read it — it usually names the valid options — and \
retry once with a corrected argument.
5. Answer in plain English for a business reader. Two short paragraphs at most. \
Cite the specific figures you used.
6. Never invent a dataset name. Call list_datasets if you are unsure what exists."""


class ChatService:
    def __init__(self, session: AsyncSession, *, claude: ClaudeService | None = None) -> None:
        self.session = session
        self.uploads = UploadRepository(session)
        self.claude = claude or ClaudeService()

    async def ask(self, request: ChatRequest, user_id: uuid.UUID) -> ChatResponse:
        # Fail before spending a model call if there is nothing to talk about.
        if await self.uploads.count_for_user(user_id) == 0:
            raise NotFoundError("No uploads found. Upload a CSV before asking questions.")

        if (
            request.upload_id is not None
            and await self.uploads.get_for_user(request.upload_id, user_id) is None
        ):
            raise NotFoundError("Upload not found.")

        toolset = AgentToolset(
            session=self.session,
            user_id=user_id,
            upload_id=request.upload_id,
        )

        messages: list[dict[str, Any]] = [
            *(turn.model_dump() for turn in request.history),
            {"role": "user", "content": request.question},
        ]

        result = await self.claude.run_agent(
            system=AGENT_SYSTEM_PROMPT,
            messages=messages,
            tools=toolset.definitions(),
            execute=toolset.execute,
            max_steps=MAX_AGENT_STEPS,
        )

        logger.info(
            "chat_answered",
            user_id=str(user_id),
            tool_calls=len(toolset.calls),
            tools_used=[call.name for call in toolset.calls],
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            duration_ms=result.duration_ms,
        )

        return ChatResponse(
            answer=result.payload,
            # The trace is the audit trail: it shows which data the answer was
            # actually built from, chosen by the model rather than by us.
            tool_calls=[
                ChatToolCall(
                    name=call.name,
                    arguments={k: str(v) for k, v in call.arguments.items()},
                    ok=call.ok,
                    summary=call.summary,
                )
                for call in toolset.calls
            ],
            sources=_sources_from_calls(toolset),
            uploads_considered=len(toolset.datasets_touched()),
        )


# Tool name -> the source kind the UI groups it under.
_SOURCE_KINDS = {
    "get_kpis": "kpi",
    "get_vendor_scores": "vendor",
    "get_country_risk": "country",
    "get_trend": "trend",
    "get_risk_breakdown": "risk",
    "get_dimension": "dimension",
    "get_operations_summary": "operations",
    "get_history": "history",
    "list_datasets": "catalog",
}


def _sources_from_calls(toolset: AgentToolset) -> list[ChatSource]:
    """Keep the existing `sources` contract, derived from what actually ran."""
    sources: list[ChatSource] = []
    for call in toolset.calls:
        if not call.ok:
            continue
        dataset = str(call.arguments.get("dataset", "")).strip()
        sources.append(
            ChatSource(
                kind=_SOURCE_KINDS.get(call.name, "metric"),
                reference=f"{dataset} / {call.name}" if dataset else call.name,
                detail=call.summary,
            )
        )
    return sources
