"""Upload queries."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.models.upload import Upload
from app.repositories.base import BaseRepository


class UploadRepository(BaseRepository[Upload]):
    model = Upload

    async def get_for_user(self, upload_id: uuid.UUID, user_id: uuid.UUID) -> Upload | None:
        """Fetch scoped to the owner.

        Every read path uses this rather than ``get()`` so an authenticated user
        cannot read another tenant's upload by guessing an ID.
        """
        stmt = select(Upload).where(Upload.id == upload_id, Upload.user_id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(
        self, user_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> list[Upload]:
        stmt = (
            select(Upload)
            .where(Upload.user_id == user_id)
            .order_by(Upload.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_for_user(self, user_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(Upload).where(Upload.user_id == user_id)
        return int((await self.session.execute(stmt)).scalar_one())

    async def list_completed_for_user(
        self, user_id: uuid.UUID, *, limit: int = 100
    ) -> list[Upload]:
        """Oldest-first — the historical trend chart reads chronologically."""
        stmt = (
            select(Upload)
            .where(Upload.user_id == user_id, Upload.status == "completed")
            .order_by(Upload.created_at.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())
