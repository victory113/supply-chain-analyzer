"""Analysis routes: poll status, read results, re-run, compare."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Query, status

from app.api.deps import CurrentUser, DbSession
from app.core.exceptions import ConflictError, NotFoundError
from app.models.analysis import Analysis
from app.models.enums import AnalysisStatus
from app.schemas.analysis import (
    AnalysisDetail,
    AnalysisRead,
    AnalysisStatusRead,
    ComparisonChange,
    ComparisonRequest,
    ComparisonResult,
)
from app.schemas.common import Page
from app.services.analysis import AnalysisService

router = APIRouter(prefix="/analyses", tags=["analyses"])


@router.get("", response_model=Page[AnalysisRead], summary="List your analyses")
async def list_analyses(
    session: DbSession,
    current_user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[AnalysisRead]:
    service = AnalysisService(session)
    rows = await service.analyses.list_for_user(current_user.id, limit=limit, offset=offset)
    return Page[AnalysisRead](
        items=[AnalysisRead.model_validate(row) for row in rows],
        total=len(rows) + offset,  # cheap upper bound; exact count isn't worth a scan
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{analysis_id}/status",
    response_model=AnalysisStatusRead,
    summary="Poll analysis progress",
)
async def analysis_status(
    analysis_id: uuid.UUID, session: DbSession, current_user: CurrentUser
) -> AnalysisStatusRead:
    """Small payload by design — the frontend polls this on a short interval."""
    analysis = await _get_owned(session, analysis_id, current_user.id)
    return AnalysisStatusRead.model_validate(analysis)


@router.get("/{analysis_id}", response_model=AnalysisDetail, summary="Full analysis result")
async def get_analysis(
    analysis_id: uuid.UUID, session: DbSession, current_user: CurrentUser
) -> AnalysisDetail:
    analysis = await _get_owned(session, analysis_id, current_user.id)
    return AnalysisDetail.model_validate(analysis)


@router.post(
    "/{analysis_id}/rerun",
    response_model=AnalysisStatusRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-run a failed or stale analysis",
)
async def rerun_analysis(
    analysis_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    background: BackgroundTasks,
) -> AnalysisStatusRead:
    analysis = await _get_owned(session, analysis_id, current_user.id)
    if analysis.status == AnalysisStatus.RUNNING:
        raise ConflictError("This analysis is already running.")

    analysis.status = AnalysisStatus.QUEUED
    analysis.error_message = None
    await session.commit()

    from app.api.v1.uploads import _enqueue_analysis

    _enqueue_analysis(analysis.id, background)
    return AnalysisStatusRead.model_validate(analysis)


@router.post("/compare", response_model=ComparisonResult, summary="Compare two uploads")
async def compare(
    payload: ComparisonRequest, session: DbSession, current_user: CurrentUser
) -> ComparisonResult:
    """Before/after diff of two datasets, e.g. either side of a disruption."""
    service = AnalysisService(session)
    before, after, result = await service.compare_uploads(
        payload.before_upload_id, payload.after_upload_id, current_user.id
    )
    return ComparisonResult(
        net_change=result.get("net_change", "MIXED"),
        summary=result.get("summary", ""),
        changes=[ComparisonChange(**change) for change in result.get("changes", [])],
        before=before,
        after=after,
    )


async def _get_owned(session: DbSession, analysis_id: uuid.UUID, user_id: uuid.UUID) -> Analysis:
    analysis = await AnalysisService(session).analyses.get_for_user(analysis_id, user_id)
    if analysis is None:
        raise NotFoundError("Analysis not found.")
    return analysis
