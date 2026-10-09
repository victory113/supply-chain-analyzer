"""Tests for the tools the chat agent can call.

The model chooses the arguments to these tools, which means the arguments are
untrusted input. The most important test here is the tenancy one: a dataset
name belonging to another account must not resolve, no matter how confidently
the model asks for it.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime

from app.core.security import hash_password
from app.models.user import User
from app.services.agent_tools import MAX_ROWS, AgentToolset
from app.services.analysis import AnalysisService

CSV = b"""shipment_id,vendor,carrier,origin_country,quantity,unit_cost,status,delay_days,shipped_on
S001,GlobalParts,Maersk,China,500,45.00,delayed,8,2024-01-15
S002,FastShip,DHL,Brazil,1200,12.50,on_time,0,2024-02-15
S003,GlobalParts,Maersk,Taiwan,250,120.00,delayed,15,2024-03-14
S004,QuickSupply,DHL,Mexico,3000,2.10,on_time,0,2024-04-15
S005,GlobalParts,Maersk,China,700,33.00,delayed,22,2024-05-11
S006,FastShip,DHL,Brazil,900,18.00,on_time,0,2024-06-02
"""

# No carrier, no prices: used to prove absent data is reported, not invented.
SPARSE_CSV = b"""vendor,origin_country,delay_days,shipped_on
Acme,China,4,2024-01-10
Acme,China,0,2024-02-10
Beta,Mexico,0,2024-03-10
Beta,Mexico,9,2024-04-10
"""


async def make_user(session, email: str) -> User:
    user = User(email=email, password_hash=hash_password("sup3r-secret-pw"))
    session.add(user)
    await session.flush()
    return user


async def upload_for(session, user, *, label: str, csv: bytes = CSV):
    service = AnalysisService(session)
    upload, _, _ = await service.create_upload(
        user_id=user.id, filename=f"{label}.csv", stream=io.BytesIO(csv), size_bytes=len(csv)
    )
    return upload


def toolset_for(session, user, upload_id=None) -> AgentToolset:
    return AgentToolset(session=session, user_id=user.id, upload_id=upload_id)


class TestTenancy:
    async def test_a_dataset_belonging_to_another_user_does_not_resolve(self, session):
        """The security property of the whole design. The model supplies a
        dataset *name*; names are matched only against the caller's uploads,
        so asking for someone else's data cannot reach it."""
        victim = await make_user(session, "victim@example.com")
        attacker = await make_user(session, "attacker@example.com")
        await upload_for(session, victim, label="victim-secret-data")
        await upload_for(session, attacker, label="my-own-data")

        tools = toolset_for(session, attacker)
        result = await tools.execute("get_kpis", {"dataset": "victim-secret-data"})

        assert "error" in result
        assert "victim-secret-data" not in result["error"].replace(
            "No dataset named 'victim-secret-data'.", ""
        )
        assert "my-own-data" in result["error"]  # lists only the caller's own

    async def test_listing_shows_only_the_callers_datasets(self, session):
        victim = await make_user(session, "victim2@example.com")
        attacker = await make_user(session, "attacker2@example.com")
        await upload_for(session, victim, label="victim-data")
        await upload_for(session, attacker, label="attacker-data")

        result = await toolset_for(session, attacker).execute("list_datasets", {})

        names = [d["name"] for d in result["datasets"]]
        assert names == ["attacker-data.csv"]

    async def test_a_pinned_upload_overrides_whatever_the_model_asks_for(self, session):
        """When the UI scopes the chat to one dataset, every tool answers from
        it even if the model names a different one."""
        user = await make_user(session, "pinned@example.com")
        first = await upload_for(session, user, label="january")
        await upload_for(session, user, label="february")

        tools = toolset_for(session, user, upload_id=first.id)
        result = await tools.execute("get_kpis", {"dataset": "february"})

        assert result["dataset"] == "january.csv"


class TestDatasetResolution:
    async def test_omitting_the_name_uses_the_most_recent_upload(self, session):
        user = await make_user(session, "recent@example.com")
        older = await upload_for(session, user, label="older")
        newer = await upload_for(session, user, label="newer")

        # Both rows are created in the same transaction, so the database
        # default timestamp can be identical and the ordering undefined. Space
        # them explicitly — this is testing "picks the latest", not the clock.
        older.created_at = datetime(2024, 1, 1, tzinfo=UTC)
        newer.created_at = datetime(2024, 6, 1, tzinfo=UTC)
        await session.flush()

        result = await toolset_for(session, user).execute("get_kpis", {})

        assert result["dataset"] == "newer.csv"

    async def test_a_shortened_name_still_matches(self, session):
        # The model routinely drops the extension.
        user = await make_user(session, "short@example.com")
        await upload_for(session, user, label="q1-shipments")

        result = await toolset_for(session, user).execute("get_kpis", {"dataset": "q1-shipments"})

        assert result["dataset"] == "q1-shipments.csv"

    async def test_an_unknown_name_returns_the_valid_options(self, session):
        """The error is written for the model to act on, not just to log."""
        user = await make_user(session, "unknown@example.com")
        await upload_for(session, user, label="real-data")

        result = await toolset_for(session, user).execute("get_kpis", {"dataset": "invented"})

        assert "invented" in result["error"]
        assert "real-data.csv" in result["error"]

    async def test_an_account_with_no_uploads_says_so(self, session):
        user = await make_user(session, "empty@example.com")
        result = await toolset_for(session, user).execute("get_kpis", {})
        assert "no uploaded datasets" in result["error"]


class TestRetrieval:
    async def test_vendor_scores_come_back_worst_first(self, session):
        user = await make_user(session, "vendors@example.com")
        await upload_for(session, user, label="data")

        result = await toolset_for(session, user).execute("get_vendor_scores", {})

        vendors = result["vendors"]
        assert vendors[0]["vendor"] == "GlobalParts"
        assert vendors[0]["health_score"] <= vendors[-1]["health_score"]

    async def test_the_row_limit_is_clamped_however_the_model_asks(self, session):
        """An argument chosen by a model is untrusted input like any other."""
        user = await make_user(session, "limits@example.com")
        await upload_for(session, user, label="data")
        tools = toolset_for(session, user)

        huge = await tools.execute("get_vendor_scores", {"limit": 10_000})
        nonsense = await tools.execute("get_country_risk", {"limit": "lots"})
        negative = await tools.execute("get_country_risk", {"limit": -5})

        assert len(huge["vendors"]) <= MAX_ROWS
        assert len(nonsense["countries"]) >= 1
        assert len(negative["countries"]) >= 1

    async def test_a_dimension_the_file_lacks_reports_that_plainly(self, session):
        """Absent data must never read as a zero result."""
        user = await make_user(session, "sparse@example.com")
        await upload_for(session, user, label="sparse", csv=SPARSE_CSV)

        result = await toolset_for(session, user).execute(
            "get_dimension", {"dimension": "carriers"}
        )

        assert result["rows"] == []
        assert "did not contain that column" in result["note"]

    async def test_a_missing_dimension_points_at_the_next_step(self, session):
        """Reporting the gap is not enough. Told only that the data is absent,
        the model stops — even when another upload has the column it needs."""
        user = await make_user(session, "sparse2@example.com")
        await upload_for(session, user, label="sparse", csv=SPARSE_CSV)

        result = await toolset_for(session, user).execute(
            "get_dimension", {"dimension": "carriers"}
        )

        assert "list_datasets" in result["note"]

    async def test_a_dimension_the_file_has_returns_rows(self, session):
        user = await make_user(session, "carriers@example.com")
        await upload_for(session, user, label="rich")

        result = await toolset_for(session, user).execute(
            "get_dimension", {"dimension": "carriers"}
        )

        assert {row["label"] for row in result["rows"]} == {"Maersk", "DHL"}

    async def test_an_invalid_dimension_names_the_valid_ones(self, session):
        user = await make_user(session, "baddim@example.com")
        await upload_for(session, user, label="data")

        result = await toolset_for(session, user).execute(
            "get_dimension", {"dimension": "astrology"}
        )

        assert "astrology" in result["error"]
        assert "carriers" in result["error"]

    async def test_risk_breakdown_names_components_it_could_not_measure(self, session):
        user = await make_user(session, "risk@example.com")
        await upload_for(session, user, label="sparse", csv=SPARSE_CSV)

        result = await toolset_for(session, user).execute("get_risk_breakdown", {})

        # No prices in the sparse file, so value_at_risk is unmeasurable and
        # must be named rather than silently missing.
        assert "value_at_risk" in result["components_not_measurable"]


class TestAuditTrail:
    async def test_every_call_is_recorded_in_order(self, session):
        user = await make_user(session, "audit@example.com")
        await upload_for(session, user, label="data")
        tools = toolset_for(session, user)

        await tools.execute("list_datasets", {})
        await tools.execute("get_vendor_scores", {})

        assert [c.name for c in tools.calls] == ["list_datasets", "get_vendor_scores"]
        assert all(c.ok for c in tools.calls)
        assert all(c.summary for c in tools.calls)

    async def test_a_failed_call_is_recorded_as_failed(self, session):
        user = await make_user(session, "audit2@example.com")
        await upload_for(session, user, label="data")
        tools = toolset_for(session, user)

        await tools.execute("get_kpis", {"dataset": "does-not-exist"})

        assert tools.calls[0].ok is False

    async def test_an_unknown_tool_is_reported_rather_than_raised(self, session):
        user = await make_user(session, "audit3@example.com")
        tools = toolset_for(session, user)

        result = await tools.execute("drop_all_tables", {})

        assert "No tool named" in result["error"]
        assert tools.calls[0].ok is False

    async def test_datasets_touched_tracks_what_was_actually_read(self, session):
        user = await make_user(session, "touched@example.com")
        await upload_for(session, user, label="data")
        tools = toolset_for(session, user)

        await tools.execute("list_datasets", {})  # reads no report
        assert tools.datasets_touched() == set()

        await tools.execute("get_kpis", {})
        assert tools.datasets_touched() == {"data.csv"}


class TestToolDefinitions:
    async def test_every_definition_is_shaped_for_the_messages_api(self, session):
        """A malformed schema is rejected by the API with a 400, which would
        break every chat request at once — so it is checked here rather than
        discovered in production."""
        user = await make_user(session, "defs@example.com")
        definitions = toolset_for(session, user).definitions()

        assert definitions
        for tool in definitions:
            assert tool["name"]
            assert tool["description"]
            schema = tool["input_schema"]
            assert schema["type"] == "object"
            assert isinstance(schema.get("properties", {}), dict)

            # Anything listed as required must actually be declared.
            properties = set(schema.get("properties", {}))
            missing = set(schema.get("required", [])) - properties
            assert not missing, f"{tool['name']} requires undeclared {missing}"

            for name, spec in schema.get("properties", {}).items():
                assert spec.get("type"), f"{tool['name']}.{name} has no type"

    async def test_tool_names_are_unique(self, session):
        user = await make_user(session, "defs3@example.com")
        names = [t["name"] for t in toolset_for(session, user).definitions()]
        assert len(names) == len(set(names))

    async def test_every_advertised_tool_has_a_handler(self, session):
        """A tool the model can see but we cannot run is a guaranteed error."""
        user = await make_user(session, "defs2@example.com")
        tools = toolset_for(session, user)

        advertised = {t["name"] for t in tools.definitions()}
        implemented = set(tools._handlers())

        assert advertised == implemented
