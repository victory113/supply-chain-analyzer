"""End-to-end tests for the chat agent, with the model scripted.

These check the wiring the unit tests cannot: that the service hands real
tools to the model, that whatever the model calls actually runs against the
database, and that the trace returned to the client reflects what happened.
"""

from __future__ import annotations

import io

from app.core.exceptions import NotFoundError
from app.core.security import hash_password
from app.models.user import User
from app.schemas.chat import ChatRequest
from app.services.analysis import AnalysisService
from app.services.chat import ChatService
from app.services.claude import LLMResult

CSV = b"""shipment_id,vendor,carrier,origin_country,quantity,unit_cost,status,delay_days,shipped_on
S001,GlobalParts,Maersk,China,500,45.00,delayed,8,2024-01-15
S002,FastShip,DHL,Brazil,1200,12.50,on_time,0,2024-02-15
S003,GlobalParts,Maersk,Taiwan,250,120.00,delayed,15,2024-03-14
S004,QuickSupply,DHL,Mexico,3000,2.10,on_time,0,2024-04-15
"""


class ScriptedAgentClaude:
    """A ClaudeService stand-in that calls a fixed list of tools, then answers.

    It exercises the real toolset — the tools run for real against the test
    database — while keeping the model's choices deterministic.
    """

    def __init__(self, plan: list[tuple[str, dict]], answer: str = "Here is the answer.") -> None:
        self.plan = plan
        self.answer = answer
        self.tools_offered: list[str] = []
        self.system: str = ""

    async def run_agent(self, *, system, messages, tools, execute, max_steps):
        self.system = system
        self.tools_offered = [t["name"] for t in tools]
        self.results = [await execute(name, args) for name, args in self.plan]
        return LLMResult(
            payload=self.answer,
            model="claude-opus-5",
            input_tokens=900,
            output_tokens=180,
            duration_ms=1500,
        )


async def make_user(session, email: str = "chat@example.com") -> User:
    user = User(email=email, password_hash=hash_password("sup3r-secret-pw"))
    session.add(user)
    await session.flush()
    return user


async def seed(session, user, label: str = "q1"):
    service = AnalysisService(session)
    upload, _, _ = await service.create_upload(
        user_id=user.id, filename=f"{label}.csv", stream=io.BytesIO(CSV), size_bytes=len(CSV)
    )
    return upload


class TestAgentWiring:
    async def test_the_model_is_offered_the_full_toolset(self, session):
        user = await make_user(session)
        await seed(session, user)
        claude = ScriptedAgentClaude(plan=[])

        await ChatService(session, claude=claude).ask(
            ChatRequest(question="How are we doing?"), user.id
        )

        assert "get_vendor_scores" in claude.tools_offered
        assert "get_country_risk" in claude.tools_offered
        assert "get_trend" in claude.tools_offered

    async def test_tools_the_model_calls_run_against_real_data(self, session):
        user = await make_user(session)
        await seed(session, user)
        claude = ScriptedAgentClaude(plan=[("get_vendor_scores", {})])

        await ChatService(session, claude=claude).ask(
            ChatRequest(question="Who is worst?"), user.id
        )

        vendors = claude.results[0]["vendors"]
        assert vendors[0]["vendor"] == "GlobalParts"

    async def test_the_trace_records_each_call_in_order(self, session):
        """A model that chooses its own retrieval has to show its working."""
        user = await make_user(session)
        await seed(session, user)
        claude = ScriptedAgentClaude(
            plan=[("list_datasets", {}), ("get_vendor_scores", {}), ("get_trend", {})]
        )

        response = await ChatService(session, claude=claude).ask(
            ChatRequest(question="Who is worst and is it improving?"), user.id
        )

        assert [c.name for c in response.tool_calls] == [
            "list_datasets",
            "get_vendor_scores",
            "get_trend",
        ]
        assert all(c.ok for c in response.tool_calls)
        assert response.answer == "Here is the answer."

    async def test_sources_are_derived_from_what_actually_ran(self, session):
        user = await make_user(session)
        await seed(session, user)
        claude = ScriptedAgentClaude(plan=[("get_country_risk", {})])

        response = await ChatService(session, claude=claude).ask(
            ChatRequest(question="Which country is riskiest?"), user.id
        )

        assert [s.kind for s in response.sources] == ["country"]

    async def test_a_failed_tool_call_is_marked_failed_in_the_trace(self, session):
        user = await make_user(session)
        await seed(session, user)
        claude = ScriptedAgentClaude(plan=[("get_kpis", {"dataset": "nonexistent"})])

        response = await ChatService(session, claude=claude).ask(
            ChatRequest(question="How did March go?"), user.id
        )

        assert response.tool_calls[0].ok is False
        # A failed call grounds nothing, so it must not appear as a source.
        assert response.sources == []

    async def test_uploads_considered_counts_datasets_actually_read(self, session):
        user = await make_user(session)
        await seed(session, user, label="q1")
        await seed(session, user, label="q2")
        claude = ScriptedAgentClaude(
            plan=[("get_kpis", {"dataset": "q1"}), ("get_kpis", {"dataset": "q2"})]
        )

        response = await ChatService(session, claude=claude).ask(
            ChatRequest(question="Compare them."), user.id
        )

        assert response.uploads_considered == 2


class TestGuardRails:
    async def test_asking_with_no_uploads_fails_before_a_model_call(self, session):
        """No point paying for a round trip to answer 'you have no data'."""
        import pytest

        user = await make_user(session, "nodata@example.com")
        claude = ScriptedAgentClaude(plan=[])

        with pytest.raises(NotFoundError):
            await ChatService(session, claude=claude).ask(
                ChatRequest(question="How are we doing?"), user.id
            )

        assert claude.tools_offered == []

    async def test_scoping_to_another_users_upload_is_rejected(self, session):
        import pytest

        owner = await make_user(session, "owner@example.com")
        intruder = await make_user(session, "intruder@example.com")
        upload = await seed(session, owner)
        claude = ScriptedAgentClaude(plan=[])

        with pytest.raises(NotFoundError):
            await ChatService(session, claude=claude).ask(
                ChatRequest(question="Show me this.", upload_id=upload.id), intruder.id
            )

    async def test_the_system_prompt_forbids_inventing_numbers(self, session):
        user = await make_user(session)
        await seed(session, user)
        claude = ScriptedAgentClaude(plan=[])

        await ChatService(session, claude=claude).ask(
            ChatRequest(question="How are we doing?"), user.id
        )

        assert "Never state a figure that did not come back from a tool" in claude.system
