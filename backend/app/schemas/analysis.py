"""AI analysis schemas.

``LLMRiskItem`` / ``LLMAnalysisPayload`` are the *contract with the model* —
they validate what Claude returns before anything is persisted. The ``*Read``
models are the API's outward shape.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import AnalysisStatus, RiskLevel
from app.schemas.analytics import AnalyticsReport
from app.schemas.common import ORMModel


class LLMRiskItem(BaseModel):
    title: str = Field(max_length=255)
    risk_level: RiskLevel
    explanation: str
    recommendation: str
    affected_items: list[str] = Field(default_factory=list, max_length=20)
    evidence_metric: str | None = Field(
        default=None,
        max_length=128,
        description="Name of the computed metric this risk is grounded in.",
    )


class LLMAnalysisPayload(BaseModel):
    """Schema Claude must conform to. Enforced via structured outputs."""

    summary: str
    risks: list[LLMRiskItem] = Field(default_factory=list, max_length=10)
    healthy_signals: list[str] = Field(default_factory=list, max_length=10)


class RiskRead(ORMModel):
    id: uuid.UUID
    position: int
    title: str
    risk_level: RiskLevel
    explanation: str | None
    recommendation: str | None
    affected_items: list[str] | None
    evidence_metric: str | None


class AnalysisRead(ORMModel):
    id: uuid.UUID
    upload_id: uuid.UUID
    status: AnalysisStatus
    summary: str | None
    overall_risk: RiskLevel | None
    risk_score: float | None
    healthy_signals: list[str] | None
    model_name: str | None
    duration_ms: int | None
    error_message: str | None
    created_at: datetime
    risks: list[RiskRead] = Field(default_factory=list)


class AnalysisDetail(AnalysisRead):
    """Analysis plus the deterministic metrics that grounded it."""

    metrics_snapshot: dict[str, Any] | None = None


class AnalysisStatusRead(ORMModel):
    """Lightweight polling payload for the frontend progress indicator."""

    id: uuid.UUID
    status: AnalysisStatus
    error_message: str | None


class ComparisonRequest(BaseModel):
    before_upload_id: uuid.UUID
    after_upload_id: uuid.UUID


class ComparisonChange(BaseModel):
    title: str
    change_type: str = Field(description="IMPROVED | WORSENED | NEW_ISSUE")
    explanation: str
    recommendation: str
    affected_items: list[str] = Field(default_factory=list)


class ComparisonResult(BaseModel):
    net_change: str
    summary: str
    changes: list[ComparisonChange]
    before: AnalyticsReport
    after: AnalyticsReport
