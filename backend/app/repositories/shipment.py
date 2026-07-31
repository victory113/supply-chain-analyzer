"""Shipment queries.

Note the split: ``list_for_upload`` streams rows for the Python analytics
engine, while ``vendor_rollup`` pushes aggregation into Postgres. The engine
owns the scoring logic; the database owns the counting when a full scan would
be wasteful.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Integer, case, func, select

from app.models.shipment import Shipment
from app.repositories.base import BaseRepository


class ShipmentRepository(BaseRepository[Shipment]):
    model = Shipment

    async def list_for_upload(
        self, upload_id: uuid.UUID, *, limit: int | None = None, offset: int = 0
    ) -> list[Shipment]:
        stmt = select(Shipment).where(Shipment.upload_id == upload_id).offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_for_upload(self, upload_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(Shipment).where(Shipment.upload_id == upload_id)
        return int((await self.session.execute(stmt)).scalar_one())

    async def bulk_insert(self, shipments: list[Shipment]) -> int:
        if not shipments:
            return 0
        self.session.add_all(shipments)
        await self.session.flush()
        return len(shipments)

    async def vendor_rollup(self, upload_id: uuid.UUID) -> list[dict[str, Any]]:
        """Vendor aggregates computed in-database, for large uploads."""
        # CASE rather than a cast of the boolean — portable across PG and SQLite.
        late = func.sum(case((Shipment.delay_days > 0, 1), else_=0).cast(Integer))
        stmt = (
            select(
                Shipment.vendor.label("vendor"),
                func.count().label("shipment_count"),
                late.label("late_count"),
                func.avg(Shipment.delay_days).label("avg_delay_days"),
                func.avg(Shipment.lead_time_days).label("avg_lead_time_days"),
            )
            .where(Shipment.upload_id == upload_id)
            .group_by(Shipment.vendor)
            .order_by(func.count().desc())
        )
        rows = (await self.session.execute(stmt)).mappings().all()
        return [dict(row) for row in rows]

    async def distinct_vendors(self, upload_id: uuid.UUID) -> list[str]:
        stmt = (
            select(Shipment.vendor)
            .where(Shipment.upload_id == upload_id, Shipment.vendor.is_not(None))
            .distinct()
        )
        return [v for v in (await self.session.execute(stmt)).scalars().all() if v]
