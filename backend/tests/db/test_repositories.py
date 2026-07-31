"""Database tests: repository queries, cascades, and ownership scoping."""

from __future__ import annotations

import uuid

from app.core.security import hash_password
from app.models.analysis import Analysis, Risk
from app.models.enums import AnalysisStatus, RiskLevel, UploadStatus
from app.models.upload import Upload
from app.models.user import User
from app.repositories.analysis import AnalysisRepository
from app.repositories.shipment import ShipmentRepository
from app.repositories.upload import UploadRepository
from app.repositories.user import UserRepository
from tests.conftest import make_shipment


async def make_user(session, email: str = "user@example.com") -> User:
    user = User(email=email, password_hash=hash_password("sup3r-secret-pw"))
    session.add(user)
    await session.flush()
    return user


async def make_upload(session, user: User, **kwargs) -> Upload:
    kwargs.setdefault("filename", "data.csv")
    upload = Upload(user_id=user.id, **kwargs)
    session.add(upload)
    await session.flush()
    return upload


class TestUserRepository:
    async def test_lookup_by_email_is_case_insensitive(self, session):
        await make_user(session, "Analyst@Example.com")
        repo = UserRepository(session)
        assert await repo.get_by_email("analyst@example.com") is not None
        assert await repo.get_by_email("ANALYST@EXAMPLE.COM") is not None

    async def test_lookup_trims_surrounding_whitespace(self, session):
        await make_user(session, "analyst@example.com")
        assert await UserRepository(session).get_by_email("  analyst@example.com ")

    async def test_missing_email_returns_none(self, session):
        assert await UserRepository(session).get_by_email("nobody@example.com") is None


class TestUploadRepository:
    async def test_get_for_user_scopes_to_the_owner(self, session):
        owner = await make_user(session, "owner@example.com")
        other = await make_user(session, "other@example.com")
        upload = await make_upload(session, owner)

        repo = UploadRepository(session)
        assert await repo.get_for_user(upload.id, owner.id) is not None
        assert await repo.get_for_user(upload.id, other.id) is None

    async def test_listing_is_newest_first(self, session):
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        user = await make_user(session)
        # Timestamps are set explicitly: two rows inserted in the same
        # transaction can share a server-generated `now()`, which would make
        # the ordering assertion pass or fail at random.
        older = await make_upload(
            session, user, filename="old.csv", created_at=now - timedelta(days=1)
        )
        newer = await make_upload(session, user, filename="new.csv", created_at=now)
        await session.commit()

        uploads = await UploadRepository(session).list_for_user(user.id)
        assert [u.id for u in uploads] == [newer.id, older.id]

    async def test_completed_listing_excludes_other_statuses(self, session):
        user = await make_user(session)
        await make_upload(session, user, status=UploadStatus.COMPLETED)
        await make_upload(session, user, status=UploadStatus.FAILED)
        await session.commit()

        completed = await UploadRepository(session).list_completed_for_user(user.id)
        assert len(completed) == 1
        assert completed[0].status == UploadStatus.COMPLETED


class TestShipmentRepository:
    async def test_bulk_insert_and_count(self, session):
        user = await make_user(session)
        upload = await make_upload(session, user)
        repo = ShipmentRepository(session)

        inserted = await repo.bulk_insert(
            [make_shipment(upload.id, shipment_ref=f"S{i}") for i in range(25)]
        )
        assert inserted == 25
        assert await repo.count_for_upload(upload.id) == 25

    async def test_bulk_insert_of_nothing_is_a_no_op(self, session):
        assert await ShipmentRepository(session).bulk_insert([]) == 0

    async def test_pagination_returns_disjoint_pages(self, session):
        user = await make_user(session)
        upload = await make_upload(session, user)
        repo = ShipmentRepository(session)
        await repo.bulk_insert([make_shipment(upload.id, shipment_ref=f"S{i}") for i in range(10)])

        first = await repo.list_for_upload(upload.id, limit=4, offset=0)
        second = await repo.list_for_upload(upload.id, limit=4, offset=4)
        assert len(first) == 4
        assert {s.id for s in first}.isdisjoint({s.id for s in second})

    async def test_distinct_vendors_ignores_nulls(self, session):
        user = await make_user(session)
        upload = await make_upload(session, user)
        repo = ShipmentRepository(session)
        await repo.bulk_insert(
            [
                make_shipment(upload.id, vendor="Acme"),
                make_shipment(upload.id, vendor="Acme"),
                make_shipment(upload.id, vendor="Beta"),
                make_shipment(upload.id, vendor=None),
            ]
        )
        assert set(await repo.distinct_vendors(upload.id)) == {"Acme", "Beta"}


class TestAnalysisRepository:
    async def test_get_for_user_scopes_through_the_upload(self, session):
        owner = await make_user(session, "owner@example.com")
        other = await make_user(session, "other@example.com")
        upload = await make_upload(session, owner)
        analysis = Analysis(upload_id=upload.id, status=AnalysisStatus.COMPLETED)
        session.add(analysis)
        await session.commit()

        repo = AnalysisRepository(session)
        assert await repo.get_for_user(analysis.id, owner.id) is not None
        assert await repo.get_for_user(analysis.id, other.id) is None

    async def test_latest_for_upload_returns_the_most_recent(self, session):
        user = await make_user(session)
        upload = await make_upload(session, user)
        for status in (AnalysisStatus.FAILED, AnalysisStatus.COMPLETED):
            session.add(Analysis(upload_id=upload.id, status=status))
            await session.flush()
        await session.commit()

        latest = await AnalysisRepository(session).latest_for_upload(upload.id)
        assert latest is not None

    async def test_replace_risks_swaps_the_whole_set(self, session):
        user = await make_user(session)
        upload = await make_upload(session, user)
        analysis = Analysis(upload_id=upload.id)
        session.add(analysis)
        await session.flush()

        repo = AnalysisRepository(session)
        await repo.replace_risks(analysis.id, [Risk(title="First", risk_level=RiskLevel.HIGH)])
        await repo.replace_risks(
            analysis.id,
            [
                Risk(title="Second", risk_level=RiskLevel.LOW),
                Risk(title="Third", risk_level=RiskLevel.MEDIUM),
            ],
        )
        await session.commit()

        refreshed = await repo.get_with_risks(analysis.id)
        assert refreshed is not None
        assert [r.title for r in refreshed.risks] == ["Second", "Third"]
        assert [r.position for r in refreshed.risks] == [1, 2]

    async def test_missing_id_returns_none_rather_than_raising(self, session):
        assert await AnalysisRepository(session).get(uuid.uuid4()) is None


class TestCascades:
    async def test_deleting_an_upload_removes_its_children(self, session):
        user = await make_user(session)
        upload = await make_upload(session, user)

        await ShipmentRepository(session).bulk_insert([make_shipment(upload.id)])
        analysis = Analysis(upload_id=upload.id)
        session.add(analysis)
        await session.flush()
        session.add(Risk(analysis_id=analysis.id, title="R", risk_level=RiskLevel.LOW))
        await session.commit()

        await session.delete(upload)
        await session.commit()

        assert await ShipmentRepository(session).count_for_upload(upload.id) == 0
        assert await AnalysisRepository(session).get(analysis.id) is None
