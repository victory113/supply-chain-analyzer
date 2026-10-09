"""Tests for the tool-using agent loop.

The loop is the part that turns a single model call into an agent: the model
may answer with "run these tools", we run them, hand the results back, and ask
again. These use a scripted stand-in for the Anthropic client so the control
flow is tested exactly, with no network and no non-determinism.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.core.exceptions import UpstreamServiceError
from app.services.claude import ClaudeService

# ── A scripted Anthropic client ───────────────────────────────────────
# Mirrors only the shape the loop consumes: .content blocks, .stop_reason,
# .usage and .model.


@dataclass
class _Text:
    text: str
    type: str = "text"


@dataclass
class _ToolUse:
    name: str
    input: dict[str, Any]
    id: str = "tu_1"
    type: str = "tool_use"


@dataclass
class _Usage:
    input_tokens: int = 100
    output_tokens: int = 50


@dataclass
class _Response:
    content: list[Any]
    stop_reason: str
    model: str = "claude-opus-5"
    usage: _Usage = field(default_factory=_Usage)


class ScriptedMessages:
    def __init__(self, script: list[_Response]) -> None:
        self.script = script
        self.requests: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> _Response:
        self.requests.append(kwargs)
        if not self.script:
            return _Response([_Text("ran out of script")], "end_turn")
        return self.script.pop(0)


class ScriptedClient:
    def __init__(self, script: list[_Response]) -> None:
        self.messages = ScriptedMessages(script)


def service_with(script: list[_Response]) -> tuple[ClaudeService, ScriptedClient]:
    client = ScriptedClient(script)
    return ClaudeService(client=client), client  # type: ignore[arg-type]


TOOLS = [{"name": "get_kpis", "description": "x", "input_schema": {"type": "object"}}]


class Recorder:
    """Stands in for the toolset; records what the loop asked it to run."""

    def __init__(self, results: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.results = results or []

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        if self.results:
            return self.results.pop(0)
        return {"ok": True}


async def run(service: ClaudeService, recorder: Recorder, *, max_steps: int = 6):
    return await service.run_agent(
        system="sys",
        messages=[{"role": "user", "content": "how are we doing?"}],
        tools=TOOLS,
        execute=recorder.execute,
        max_steps=max_steps,
    )


class TestSingleStep:
    async def test_an_answer_with_no_tools_returns_immediately(self):
        service, client = service_with([_Response([_Text("All good.")], "end_turn")])
        recorder = Recorder()

        result = await run(service, recorder)

        assert result.payload == "All good."
        assert recorder.calls == []
        assert len(client.messages.requests) == 1

    async def test_one_tool_call_then_an_answer(self):
        service, client = service_with(
            [
                _Response([_ToolUse("get_kpis", {"dataset": "q1"})], "tool_use"),
                _Response([_Text("44% of shipments were late.")], "end_turn"),
            ]
        )
        recorder = Recorder()

        result = await run(service, recorder)

        assert recorder.calls == [("get_kpis", {"dataset": "q1"})]
        assert result.payload == "44% of shipments were late."
        assert len(client.messages.requests) == 2


class TestMultiStep:
    async def test_the_model_can_chain_calls_that_depend_on_each_other(self):
        """The whole point of the upgrade: a second lookup chosen *after*
        seeing the first result, which a keyword router could never do."""
        service, _ = service_with(
            [
                _Response([_ToolUse("get_vendor_scores", {}, id="a")], "tool_use"),
                _Response([_ToolUse("get_trend", {"dataset": "q1"}, id="b")], "tool_use"),
                _Response([_Text("Acme is worst, and worsening.")], "end_turn"),
            ]
        )
        recorder = Recorder()

        result = await run(service, recorder)

        assert [name for name, _ in recorder.calls] == ["get_vendor_scores", "get_trend"]
        assert "worsening" in result.payload

    async def test_several_tools_in_one_turn_all_run(self):
        service, client = service_with(
            [
                _Response(
                    [
                        _ToolUse("get_kpis", {}, id="a"),
                        _ToolUse("get_trend", {}, id="b"),
                    ],
                    "tool_use",
                ),
                _Response([_Text("Done.")], "end_turn"),
            ]
        )
        recorder = Recorder()

        await run(service, recorder)

        assert len(recorder.calls) == 2
        # The API requires one result block per tool_use id, in one message.
        follow_up = client.messages.requests[1]["messages"][-1]
        assert follow_up["role"] == "user"
        assert [block["tool_use_id"] for block in follow_up["content"]] == ["a", "b"]

    async def test_token_usage_is_summed_across_every_step(self):
        service, _ = service_with(
            [
                _Response([_ToolUse("get_kpis", {})], "tool_use"),
                _Response([_Text("ok")], "end_turn"),
            ]
        )
        result = await run(service, Recorder())
        assert result.input_tokens == 200  # 100 per step
        assert result.output_tokens == 100


class TestFailureHandling:
    async def test_a_tool_error_is_passed_back_as_data_so_the_model_recovers(self):
        """A raising tool would end the conversation. A tool that *reports* a
        problem lets the model correct itself, which is what real ones do."""
        service, _ = service_with(
            [
                _Response([_ToolUse("get_kpis", {"dataset": "nope"})], "tool_use"),
                _Response([_ToolUse("get_kpis", {"dataset": "q1"})], "tool_use"),
                _Response([_Text("Recovered.")], "end_turn"),
            ]
        )
        recorder = Recorder(results=[{"error": "No dataset named 'nope'."}, {"ok": True}])

        result = await run(service, recorder)

        assert len(recorder.calls) == 2
        assert result.payload == "Recovered."

    async def test_the_step_limit_stops_an_endless_tool_loop(self):
        """Without a bound, a model that keeps asking for tools would run until
        the request times out, paying for a round trip each time.

        At the limit the loop asks once more with tools withheld, so the user
        gets an answer built from what was already gathered.
        """
        script = [_Response([_ToolUse("get_kpis", {})], "tool_use") for _ in range(3)]
        script.append(_Response([_Text("Forced answer.")], "end_turn"))
        service, _ = service_with(script)
        recorder = Recorder()

        result = await run(service, recorder, max_steps=3)

        assert len(recorder.calls) == 3
        assert result.payload == "Forced answer."

    async def test_a_silent_model_at_the_step_limit_still_returns_something(self):
        # Rather than an exception or a blank bubble in the UI.
        script = [_Response([_ToolUse("get_kpis", {})], "tool_use") for _ in range(4)]
        service, _ = service_with(script)

        result = await run(service, Recorder(), max_steps=3)

        assert "step limit" in result.payload

    async def test_a_refusal_is_surfaced_as_an_upstream_error(self):
        service, _ = service_with([_Response([], "refusal")])
        with pytest.raises(UpstreamServiceError):
            await run(service, Recorder())

    async def test_an_empty_answer_is_an_error_not_a_blank_reply(self):
        service, _ = service_with([_Response([_Text("   ")], "end_turn")])
        with pytest.raises(UpstreamServiceError):
            await run(service, Recorder())


class TestConversationShape:
    async def test_the_assistants_tool_request_is_echoed_back_verbatim(self):
        """The API rejects a tool_result whose matching tool_use isn't in the
        transcript, so the assistant turn has to be replayed unchanged."""
        tool_use = _ToolUse("get_kpis", {"dataset": "q1"}, id="xyz")
        service, client = service_with(
            [
                _Response([tool_use], "tool_use"),
                _Response([_Text("ok")], "end_turn"),
            ]
        )

        await run(service, Recorder())

        second = client.messages.requests[1]["messages"]
        assistant_turn = second[-2]
        assert assistant_turn["role"] == "assistant"
        assert assistant_turn["content"] == [tool_use]

    async def test_tools_are_withheld_on_the_forced_final_answer(self):
        script = [_Response([_ToolUse("get_kpis", {})], "tool_use") for _ in range(3)]
        script.append(_Response([_Text("Final.")], "end_turn"))
        service, client = service_with(script)

        await run(service, Recorder(), max_steps=2)

        assert "tools" not in client.messages.requests[-1]
