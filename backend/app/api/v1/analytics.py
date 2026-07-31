"""Analytics routes.

Every figure returned here is computed in Python by the analytics engine — no
model call is made, so these endpoints stay fast and available even when the
LLM is not.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession
from app.core.exceptions import NotFoundError
from app.schemas.analytics import (
    AnalyticsReport,
    CountryRisk,
    HistoricalReport,
    KpiSummary,
    RiskBreakdown,
    TrendAnalysis,
    VendorScore,
)
from app.services.analysis import AnalysisService

router = APIRouter(prefix="/analytics", tags=["analytics"])


async def _report(session: DbSession, upload_id: uuid.UUID, user_id: uuid.UUID) -> AnalyticsReport:
    service = AnalysisService(session)
    if await service.uploads.get_for_user(upload_id, user_id) is None:
        raise NotFoundError("Upload not found.")
    return await service.build_report(upload_id)


@router.get(
    "/uploads/{upload_id}",
    response_model=AnalyticsReport,
    summary="Full computed analytics report",
)
async def full_report(
    upload_id: uuid.UUID, session: DbSession, current_user: CurrentUser
) -> AnalyticsReport:
    return await _report(session, upload_id, current_user.id)


@router.get("/uploads/{upload_id}/kpis", response_model=KpiSummary, summary="Headline KPIs")
async def kpis(upload_id: uuid.UUID, session: DbSession, current_user: CurrentUser) -> KpiSummary:
    return (await _report(session, upload_id, current_user.id)).kpis


@router.get(
    "/uploads/{upload_id}/vendors",
    response_model=list[VendorScore],
    summary="Vendor health ranking (worst first)",
)
async def vendors(
    upload_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    limit: int = Query(default=25, ge=1, le=200),
) -> list[VendorScore]:
    return (await _report(session, upload_id, current_user.id)).vendors[:limit]


@router.get(
    "/uploads/{upload_id}/countries",
    response_model=list[CountryRisk],
    summary="Origin-country risk (riskiest first)",
)
async def countries(
    upload_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    limit: int = Query(default=25, ge=1, le=200),
) -> list[CountryRisk]:
    return (await _report(session, upload_id, current_user.id)).countries[:limit]


@router.get(
    "/uploads/{upload_id}/trend",
    response_model=TrendAnalysis,
    summary="Monthly delay trend",
)
async def trend(
    upload_id: uuid.UUID, session: DbSession, current_user: CurrentUser
) -> TrendAnalysis:
    return (await _report(session, upload_id, current_user.id)).trend


@router.get(
    "/uploads/{upload_id}/risk",
    response_model=RiskBreakdown,
    summary="Composite risk score and its drivers",
)
async def risk(
    upload_id: uuid.UUID, session: DbSession, current_user: CurrentUser
) -> RiskBreakdown:
    return (await _report(session, upload_id, current_user.id)).risk


@router.get(
    "/history",
    response_model=HistoricalReport,
    summary="How the supply chain changed across all uploads",
)
async def history(session: DbSession, current_user: CurrentUser) -> HistoricalReport:
    return await AnalysisService(session).build_history(current_user.id)
