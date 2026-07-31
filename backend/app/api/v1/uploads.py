"""Upload routes: ingest a CSV and queue its analysis."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, UploadFile, status

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.exceptions import NotFoundError, PayloadTooLargeError
from app.core.logging import get_logger
from app.schemas.analysis import AnalysisDetail
from app.schemas.common import MessageResponse, Page
from app.schemas.upload import IngestReport, ShipmentRead, UploadAccepted, UploadRead
from app.services.analysis import AnalysisService
from app.utils import cache

logger = get_logger(__name__)
router = APIRouter(prefix="/uploads", tags=["uploads"])

SAMPLE_CSV = """shipment_id,vendor,product,origin_country,destination,quantity,unit_cost,\
lead_time_days,status,delay_days,shipped_on
S001,GlobalParts Co,Circuit Boards,China,Dallas TX,500,45.00,14,delayed,8,2024-01-15
S002,FastShip Ltd,Steel Rods,Brazil,Houston TX,1200,12.50,7,on_time,0,2024-01-15
S003,GlobalParts Co,Microchips,Taiwan,Austin TX,250,120.00,21,delayed,15,2024-01-14
S004,QuickSupply,Packaging,Mexico,Dallas TX,3000,2.10,3,on_time,0,2024-02-15
S005,GlobalParts Co,Sensors,China,Houston TX,180,67.00,18,delayed,12,2024-02-13
S006,FastShip Ltd,Aluminum Sheets,Canada,Austin TX,800,8.75,5,on_time,0,2024-02-15
S007,RareMetals Inc,Lithium Cells,Argentina,Dallas TX,100,340.00,30,critical,22,2024-03-10
S008,QuickSupply,Foam Padding,Mexico,Houston TX,2500,1.50,4,on_time,0,2024-03-15
S009,RareMetals Inc,Cobalt Alloy,Congo,Austin TX,60,890.00,45,critical,18,2024-03-08
S010,GlobalParts Co,PCB Assemblies,China,Dallas TX,350,78.00,16,delayed,9,2024-04-14
S011,FastShip Ltd,Steel Rods,Brazil,Dallas TX,900,12.75,7,on_time,0,2024-04-20
S012,QuickSupply,Labels,Mexico,Austin TX,5000,0.30,3,on_time,0,2024-04-22
"""


@router.get("/sample", summary="Download a sample CSV")
async def sample_data() -> dict[str, str]:
    """Lets a new user try the product before wiring up their own export."""
    return {"csv": SAMPLE_CSV, "filename": "sample_supply_chain.csv"}


@router.post(
    "",
    response_model=UploadAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a CSV and queue an AI analysis",
)
async def create_upload(
    session: DbSession,
    current_user: CurrentUser,
    background: BackgroundTasks,
    file: UploadFile = File(..., description="Supply chain CSV export"),
    label: str | None = Form(default=None, description="Friendly name for this dataset"),
) -> UploadAccepted:
    """Parses and stores the file synchronously, then hands the slow part off.

    Returns 202 rather than 200: the rows are durably saved, but the model call
    is still pending. Poll ``poll_url`` for the analysis status.
    """
    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise PayloadTooLargeError(
            f"File exceeds the {settings.max_upload_bytes // 1_048_576} MB limit."
        )

    service = AnalysisService(session)
    upload, analysis, _ = await service.create_upload(
        user_id=current_user.id,
        filename=file.filename or "upload.csv",
        content=content,
        label=label,
    )

    task_id = _enqueue_analysis(analysis.id, background)

    return UploadAccepted(
        upload=UploadRead.model_validate(upload),
        analysis_id=analysis.id,
        task_id=task_id,
        poll_url=f"{settings.api_v1_prefix}/analyses/{analysis.id}/status",
    )


def _enqueue_analysis(analysis_id: uuid.UUID, background: BackgroundTasks) -> str | None:
    """Queue the analysis, falling back to an in-process background task.

    The fallback keeps single-container deployments (and local dev without a
    worker) functional; the response shape is identical either way, so the
    frontend polls the same endpoint regardless.
    """
    from app.workers.broker import broker_reachable
    from app.workers.tasks import run_analysis_task

    if not broker_reachable():
        # Probing first is what makes the fallback fast — see workers/broker.py
        # for why Celery cannot be relied on to fail quickly here.
        logger.info("broker_unavailable_using_inline_fallback", analysis_id=str(analysis_id))
        background.add_task(run_analysis_task.run, str(analysis_id))
        return None

    try:
        # retry=False disables publish retry for the narrow race where the
        # broker dies between the probe and this call.
        async_result = run_analysis_task.apply_async(args=[str(analysis_id)], retry=False)
        return str(async_result.id)
    except Exception as exc:
        logger.warning(
            "celery_enqueue_failed_using_inline_fallback",
            analysis_id=str(analysis_id),
            error=str(exc),
        )
        background.add_task(run_analysis_task.run, str(analysis_id))
        return None


@router.get("", response_model=Page[UploadRead], summary="List your uploads")
async def list_uploads(
    session: DbSession,
    current_user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Page[UploadRead]:
    service = AnalysisService(session)
    uploads = await service.uploads.list_for_user(current_user.id, limit=limit, offset=offset)
    total = await service.uploads.count_for_user(current_user.id)
    return Page[UploadRead](
        items=[UploadRead.model_validate(u) for u in uploads],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{upload_id}", response_model=UploadRead, summary="Fetch one upload")
async def get_upload(
    upload_id: uuid.UUID, session: DbSession, current_user: CurrentUser
) -> UploadRead:
    upload = await AnalysisService(session).uploads.get_for_user(upload_id, current_user.id)
    if upload is None:
        raise NotFoundError("Upload not found.")
    return UploadRead.model_validate(upload)


@router.get(
    "/{upload_id}/shipments",
    response_model=Page[ShipmentRead],
    summary="Paginated shipment rows",
)
async def list_shipments(
    upload_id: uuid.UUID,
    session: DbSession,
    current_user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Page[ShipmentRead]:
    service = AnalysisService(session)
    if await service.uploads.get_for_user(upload_id, current_user.id) is None:
        raise NotFoundError("Upload not found.")

    rows = await service.shipments.list_for_upload(upload_id, limit=limit, offset=offset)
    total = await service.shipments.count_for_upload(upload_id)
    return Page[ShipmentRead](
        items=[ShipmentRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{upload_id}/analysis",
    response_model=AnalysisDetail,
    summary="Latest analysis for an upload",
)
async def latest_analysis(
    upload_id: uuid.UUID, session: DbSession, current_user: CurrentUser
) -> AnalysisDetail:
    """Resolve an upload to its most recent analysis.

    A client that has an upload ID (from a list, or a bookmarked URL) otherwise
    has no way to find the matching analysis without scanning every one.
    """
    service = AnalysisService(session)
    if await service.uploads.get_for_user(upload_id, current_user.id) is None:
        raise NotFoundError("Upload not found.")

    analysis = await service.analyses.latest_for_upload(upload_id)
    if analysis is None:
        raise NotFoundError("No analysis has been run for this upload yet.")
    return AnalysisDetail.model_validate(analysis)


@router.get(
    "/{upload_id}/ingest-report",
    response_model=IngestReport,
    summary="How the file was parsed",
)
async def ingest_report(
    upload_id: uuid.UUID, session: DbSession, current_user: CurrentUser
) -> IngestReport:
    upload = await AnalysisService(session).uploads.get_for_user(upload_id, current_user.id)
    if upload is None:
        raise NotFoundError("Upload not found.")

    # The full column map lives in the analysis snapshot; this summary is
    # reconstructed from the counts stored on the upload row itself.
    return IngestReport(
        accepted_rows=upload.row_count,
        rejected_rows=upload.rejected_row_count,
        detected_columns={},
        unmapped_columns=[],
        warnings=[upload.error_message] if upload.error_message else [],
    )


@router.delete("/{upload_id}", response_model=MessageResponse, summary="Delete an upload")
async def delete_upload(
    upload_id: uuid.UUID, session: DbSession, current_user: CurrentUser
) -> MessageResponse:
    service = AnalysisService(session)
    upload = await service.uploads.get_for_user(upload_id, current_user.id)
    if upload is None:
        raise NotFoundError("Upload not found.")

    # Shipments, analyses, and risks go with it via ON DELETE CASCADE.
    await session.delete(upload)
    await session.commit()
    await cache.cache_delete(
        cache.analytics_key(str(upload_id)), cache.history_key(str(current_user.id))
    )
    return MessageResponse(message="Upload deleted.")
