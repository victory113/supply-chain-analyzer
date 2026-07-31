"""A single CSV ingestion event and its lifecycle state."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import GUID, Base, TimestampMixin
from app.models.enums import UploadStatus

if TYPE_CHECKING:
    from app.models.analysis import Analysis
    from app.models.shipment import Shipment
    from app.models.user import User


class Upload(Base, TimestampMixin):
    __tablename__ = "uploads"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Rows that parsed but failed validation — surfaced so users can fix their export.
    rejected_row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=UploadStatus.PENDING, index=True, nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(String(255))

    user: Mapped[User] = relationship(back_populates="uploads")
    shipments: Mapped[list[Shipment]] = relationship(
        back_populates="upload", cascade="all, delete-orphan"
    )
    analyses: Mapped[list[Analysis]] = relationship(
        back_populates="upload", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Upload {self.filename} ({self.status})>"
