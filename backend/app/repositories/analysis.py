"""Analysis and risk queries."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.analysis import Analysis, Risk
from app.models.upload import Upload
from app.repositories.base import BaseRepository


class AnalysisRepository(BaseRepository[Analysis]):
    model = Analysis

    async def get_with_risks(self, analysis_id: uuid.UUID) -> Analysis | None:
        stmt = (
            select(Analysis).where(Analysis.id == analysis_id).options(selectinload(Analysis.risks))
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_for_user(self, analysis_id: uuid.UUID, user_id: uuid.UUID) -> Analysis | None:
        """Join through uploads so ownership is enforced in a single query."""
        stmt = (
            select(Analysis)
            .join(Upload, Upload.id == Analysis.upload_id)
            .where(Analysis.id == analysis_id, Upload.user_id == user_id)
            .options(selectinload(Analysis.risks))
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def latest_for_upload(self, upload_id: uuid.UUID) -> Analysis | None:
        stmt = (
            select(Analysis)
            .where(Analysis.upload_id == upload_id)
            .order_by(Analysis.created_at.desc())
            .limit(1)
            .options(selectinload(Analysis.risks))
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(
        self, user_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> list[Analysis]:
        stmt = (
            select(Analysis)
            .join(Upload, Upload.id == Analysis.upload_id)
            .where(Upload.user_id == user_id)
            .order_by(Analysis.created_at.desc())
            .limit(limit)
            .offset(offset)
            .options(selectinload(Analysis.risks))
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def replace_risks(self, analysis_id: uuid.UUID, risks: list[Risk]) -> None:
        """Swap in a fresh risk set — used when an analysis is re-run."""
        existing = (
            (await self.session.execute(select(Risk).where(Risk.analysis_id == analysis_id)))
            .scalars()
            .all()
        )
        for risk in existing:
            await self.session.delete(risk)
        for position, risk in enumerate(risks, start=1):
            risk.analysis_id = analysis_id
            risk.position = position
            self.session.add(risk)
        await self.session.flush()
