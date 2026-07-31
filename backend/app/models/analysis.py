"""AI analysis run and the individual risks it produced."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import GUID, Base, TimestampMixin
from app.models.enums import AnalysisStatus, RiskLevel

if TYPE_CHECKING:
    from app.models.upload import Upload

# JSONB on Postgres, plain JSON on SQLite (tests).
JSONType = JSON().with_variant(JSONB(), "postgresql")


class Analysis(Base, TimestampMixin):
    __tablename__ = "analyses"

    upload_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("uploads.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), default=AnalysisStatus.QUEUED, index=True, nullable=False
    )
    summary: Mapped[str | None] = mapped_column(Text)
    overall_risk: Mapped[str | None] = mapped_column(String(16))
    # Deterministic score from the analytics engine — computed in Python, not by
    # the model, so it is reproducible and auditable.
    risk_score: Mapped[float | None] = mapped_column()
    healthy_signals: Mapped[list[str] | None] = mapped_column(JSONType)
    # Snapshot of the metrics fed into the prompt, so a stored analysis can be
    # explained after the fact without recomputing.
    metrics_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONType)

    model_name: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    task_id: Mapped[str | None] = mapped_column(String(128), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)

    upload: Mapped[Upload] = relationship(back_populates="analyses")
    risks: Mapped[list[Risk]] = relationship(
        back_populates="analysis",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Risk.position",
    )

    def __repr__(self) -> str:
        return f"<Analysis {self.id} {self.status}>"


class Risk(Base, TimestampMixin):
    __tablename__ = "risks"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("analyses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    risk_level: Mapped[str] = mapped_column(
        String(16), default=RiskLevel.MEDIUM, index=True, nullable=False
    )
    explanation: Mapped[str | None] = mapped_column(Text)
    recommendation: Mapped[str | None] = mapped_column(Text)
    affected_items: Mapped[list[str] | None] = mapped_column(JSONType)
    # Which computed metric the model cited — the traceability link that keeps
    # recommendations grounded in real data.
    evidence_metric: Mapped[str | None] = mapped_column(String(128))

    analysis: Mapped[Analysis] = relationship(back_populates="risks")

    def __repr__(self) -> str:
        return f"<Risk {self.risk_level} {self.title}>"
