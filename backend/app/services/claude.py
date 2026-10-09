"""Anthropic Claude client wrapper.

Everything model-facing is isolated here: the SDK client, structured-output
schemas, retry policy, and token accounting. Callers get validated Pydantic
objects and never see an SDK type.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

import anthropic
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.core.config import settings
from app.core.exceptions import UpstreamServiceError
from app.core.logging import get_logger
from app.schemas.analysis import LLMAnalysisPayload
from app.schemas.analytics import AnalyticsReport
from app.services.prompts import (
    SYSTEM_PROMPT,
    build_analysis_prompt,
    build_chat_prompt,
    build_comparison_prompt,
)

logger = get_logger(__name__)

PayloadT = TypeVar("PayloadT", bound=BaseModel)
ResultT = TypeVar("ResultT")


class LLMComparisonPayload(BaseModel):
    """Structured shape for the before/after comparison response."""

    net_change: str
    summary: str
    changes: list[dict[str, Any]]


@dataclass(frozen=True)
class LLMResult(Generic[ResultT]):
    """A parsed model response plus the usage metadata we persist."""

    payload: ResultT
    model: str
    input_tokens: int
    output_tokens: int
    duration_ms: int


def _json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic schema adjusted for the structured-outputs constraints.

    The API requires `additionalProperties: false` on every object and does not
    support numeric/length constraints, so those are stripped rather than left
    to fail at request time.
    """
    schema = model.model_json_schema()

    def _strip(node: Any) -> Any:
        if isinstance(node, dict):
            node.pop("maxLength", None)
            node.pop("minLength", None)
            node.pop("maxItems", None)
            node.pop("minItems", None)
            if node.get("type") == "object":
                node["additionalProperties"] = False
            return {key: _strip(value) for key, value in node.items()}
        if isinstance(node, list):
            return [_strip(item) for item in node]
        return node

    return _strip(schema)


class ClaudeService:
    """Thin, testable wrapper around the Anthropic Messages API."""

    def __init__(self, client: anthropic.AsyncAnthropic | None = None) -> None:
        self._client = client
        self.model = settings.anthropic_model

    @property
    def client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            if not settings.anthropic_api_key:
                raise UpstreamServiceError("ANTHROPIC_API_KEY is not configured on the server.")
            self._client = anthropic.AsyncAnthropic(
                api_key=settings.anthropic_api_key,
                timeout=settings.anthropic_timeout_seconds,
                max_retries=2,  # SDK retries 429/5xx with backoff
            )
        return self._client

    async def _structured_call(
        self,
        *,
        prompt: str,
        schema_model: type[PayloadT],
        system: str = SYSTEM_PROMPT,
        effort: str = "medium",
    ) -> LLMResult[PayloadT]:
        started = time.perf_counter()
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=settings.anthropic_max_tokens,
                system=system,
                output_config={
                    "effort": effort,
                    "format": {
                        "type": "json_schema",
                        "schema": _json_schema(schema_model),
                    },
                },
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIStatusError as exc:
            logger.error("claude_api_error", status=exc.status_code, message=str(exc))
            raise UpstreamServiceError(
                f"The analysis model returned an error ({exc.status_code})."
            ) from exc
        except anthropic.APIConnectionError as exc:
            logger.error("claude_connection_error", message=str(exc))
            raise UpstreamServiceError("Could not reach the analysis model.") from exc

        duration_ms = int((time.perf_counter() - started) * 1000)

        # A safety refusal returns HTTP 200 with an empty/partial body, so check
        # stop_reason before touching content.
        if response.stop_reason == "refusal":
            raise UpstreamServiceError("The analysis model declined to process this request.")

        text = next((block.text for block in response.content if block.type == "text"), "")
        if not text.strip():
            raise UpstreamServiceError("The analysis model returned an empty response.")

        try:
            payload = schema_model.model_validate(json.loads(text))
        except (json.JSONDecodeError, PydanticValidationError) as exc:
            logger.error("claude_payload_invalid", error=str(exc), raw=text[:500])
            raise UpstreamServiceError(
                "The analysis model returned a response we could not parse."
            ) from exc

        return LLMResult(
            payload=payload,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            duration_ms=duration_ms,
        )

    async def analyze(self, report: AnalyticsReport) -> LLMResult[LLMAnalysisPayload]:
        return await self._structured_call(
            prompt=build_analysis_prompt(report),
            schema_model=LLMAnalysisPayload,
        )

    async def compare(
        self, before: AnalyticsReport, after: AnalyticsReport
    ) -> LLMResult[LLMComparisonPayload]:
        return await self._structured_call(
            prompt=build_comparison_prompt(before, after),
            schema_model=LLMComparisonPayload,
        )

    async def run_agent(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        execute: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
        max_steps: int = 6,
    ) -> LLMResult[str]:
        """Let the model choose which tools to call, over several steps.

        The loop is the whole idea. A normal call is one request and one reply;
        here the model may answer with "call these tools instead", we run them,
        hand back the results, and ask again. It repeats until the model
        produces prose instead of another tool request.

        ``max_steps`` is a hard stop. Without it a model that keeps requesting
        tools would loop until the request times out, and each step costs a
        full round trip — so the bound is a cost and latency control, not just
        a safety net.
        """
        started = time.perf_counter()
        conversation = list(messages)
        input_tokens = 0
        output_tokens = 0
        model_name = self.model

        for step in range(max_steps):
            try:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=settings.anthropic_max_tokens,
                    system=system,
                    tools=tools,
                    messages=conversation,  # type: ignore[arg-type]
                )
            except anthropic.APIStatusError as exc:
                logger.error("claude_agent_error", status=exc.status_code, step=step)
                raise UpstreamServiceError(
                    f"The assistant returned an error ({exc.status_code})."
                ) from exc
            except anthropic.APIConnectionError as exc:
                logger.error("claude_agent_connection_error", step=step)
                raise UpstreamServiceError("Could not reach the assistant.") from exc

            input_tokens += response.usage.input_tokens
            output_tokens += response.usage.output_tokens
            model_name = response.model

            if response.stop_reason == "refusal":
                raise UpstreamServiceError("The assistant declined to answer that.")

            if response.stop_reason != "tool_use":
                text = "".join(
                    block.text for block in response.content if block.type == "text"
                ).strip()
                if not text:
                    raise UpstreamServiceError("The assistant returned an empty response.")
                return LLMResult(
                    payload=text,
                    model=model_name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )

            # The model asked for tools. Echo its message back verbatim, then
            # append one result block per request — the API requires a result
            # for every tool_use id, in the same user message.
            conversation.append({"role": "assistant", "content": response.content})
            results: list[dict[str, Any]] = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                output = await execute(block.name, dict(block.input or {}))
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(output, default=str),
                    }
                )
            conversation.append({"role": "user", "content": results})

        # Out of steps. Ask once more with tools withheld, so the user gets an
        # answer from what was already gathered rather than an error.
        logger.warning("claude_agent_step_limit", max_steps=max_steps)
        conversation.append(
            {
                "role": "user",
                "content": (
                    "Stop calling tools and answer now using only what you have "
                    "already retrieved. If it is not enough, say exactly what is missing."
                ),
            }
        )
        final = await self.client.messages.create(
            model=self.model,
            max_tokens=settings.anthropic_max_tokens,
            system=system,
            messages=conversation,  # type: ignore[arg-type]
        )
        input_tokens += final.usage.input_tokens
        output_tokens += final.usage.output_tokens
        text = "".join(b.text for b in final.content if b.type == "text").strip()
        return LLMResult(
            payload=text or "I could not complete that question within the step limit.",
            model=final.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    async def answer_question(
        self,
        question: str,
        context: str,
        *,
        uploads_considered: int,
        history: list[dict[str, str]] | None = None,
    ) -> LLMResult[str]:
        """Free-text answer grounded in retrieved metrics (no schema enforced)."""
        started = time.perf_counter()
        messages: list[dict[str, Any]] = [
            *(history or []),
            {
                "role": "user",
                "content": build_chat_prompt(question, context, uploads_considered),
            },
        ]

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=settings.anthropic_max_tokens,
                system=SYSTEM_PROMPT,
                output_config={"effort": "medium"},
                messages=messages,
            )
        except anthropic.APIError as exc:
            logger.error("claude_chat_error", message=str(exc))
            raise UpstreamServiceError("The assistant is unavailable right now.") from exc

        if response.stop_reason == "refusal":
            raise UpstreamServiceError("The assistant declined to answer that.")

        text = "".join(block.text for block in response.content if block.type == "text").strip()

        return LLMResult(
            payload=text,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
