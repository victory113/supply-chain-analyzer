"""Upload ingestion and AI analysis orchestration.

The split that matters: :meth:`AnalysisService.build_report` is pure analytics
(fast, deterministic, always available), while :meth:`run_analysis` adds the
LLM narration on top. If Claude is down, the dashboard still works.
"""

from __future__ import annotations

import uuid
from typing import IO

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UpstreamServiceError, ValidationError
from app.core.logging import get_logger
from app.models.analysis import Analysis, Risk
from app.models.enums import AnalysisStatus, UploadStatus
from app.models.upload import Upload
from app.repositories.analysis import AnalysisRepository
from app.repositories.shipment import ShipmentRepository
from app.repositories.upload import UploadRepository
from app.schemas.analytics import (
    AnalyticsReport,
    HistoricalPoint,
    HistoricalReport,
)
from app.schemas.upload import IngestReport
from app.services.analytics import ShipmentFact, build_historical_report, build_report
from app.services.claude import ClaudeService
from app.services.csv_ingest import CsvIngestService, IngestStats
from app.utils import cache

logger = get_logger(__name__)


class AnalysisService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        claude: ClaudeService | None = None,
        ingest: CsvIngestService | None = None,
    ) -> None:
        self.session = session
        self.uploads = UploadRepository(session)
        self.shipments = ShipmentRepository(session)
        self.analyses = AnalysisRepository(session)
        # Injected so tests can substitute a stub without patching imports.
        self.claude = claude or ClaudeService()
        self.ingest = ingest or CsvIngestService()

    # ── Ingestion ──────────────────────────────────────────────────────

    async def create_upload(
        self,
        *,
        user_id: uuid.UUID,
        filename: str,
        stream: IO[bytes],
        size_bytes: int,
        label: str | None = None,
    ) -> tuple[Upload, Analysis, IngestReport]:
        """Parse, persist, and queue an analysis. Runs inside the request.

        Consumes the upload as a stream and flushes each batch, so peak memory
        tracks the batch size rather than the file size — a 100 MB CSV costs
        roughly what a 1 MB one does.
        """
        if not filename.lower().endswith(".csv"):
            raise ValidationError("Only .csv files are supported.")

        upload = Upload(
            user_id=user_id,
            filename=filename[:512],
            label=label,
            size_bytes=size_bytes,
            status=UploadStatus.PARSING,
        )
        await self.uploads.add(upload)

        stats = IngestStats()
        for batch in self.ingest.stream_batches(stream, upload.id, stats):
            self.session.add_all(batch)
            # Flush per batch, then release just these rows from the identity
            # map. Expunging the whole session would detach `upload` too and
            # silently drop the row counts set below.
            await self.session.flush()
            for shipment in batch:
                self.session.expunge(shipment)

        upload.row_count = stats.accepted
        upload.rejected_row_count = stats.rejected
        upload.status = UploadStatus.ANALYZING

        analysis = Analysis(upload_id=upload.id, status=AnalysisStatus.QUEUED)
        await self.analyses.add(analysis)
        await self.session.commit()

        logger.info(
            "upload_created",
            upload_id=str(upload.id),
            rows=stats.accepted,
            rejected=stats.rejected,
            derived_delays=stats.derived_delays,
            truncated=stats.truncated,
        )
        return upload, analysis, stats.to_report()

    # ── Deterministic analytics ────────────────────────────────────────

    async def build_report(
        self, upload_id: uuid.UUID, *, use_cache: bool = True
    ) -> AnalyticsReport:
        key = cache.analytics_key(str(upload_id))
        if use_cache:
            cached = await cache.cache_get(key)
            if cached:
                return AnalyticsReport.model_validate(cached)

        rows = await self.shipments.list_for_upload(upload_id)
        if not rows:
            raise NotFoundError("No shipment data found for this upload.")

        report = build_report(str(upload_id), ShipmentFact.from_models(rows))
        await cache.cache_set(key, report.model_dump(mode="json"))
        return report

    async def build_history(self, user_id: uuid.UUID) -> HistoricalReport:
        """Cross-upload trend, assembled from stored analyses.

        Reads the persisted ``risk_score``/``metrics_snapshot`` rather than
        re-scanning shipments, so this stays cheap as history grows.
        """
        key = cache.history_key(str(user_id))
        cached = await cache.cache_get(key)
        if cached:
            return HistoricalReport.model_validate(cached)

        uploads = await self.uploads.list_completed_for_user(user_id)
        points: list[HistoricalPoint] = []

        for upload in uploads:
            analysis = await self.analyses.latest_for_upload(upload.id)
            if analysis is None or analysis.risk_score is None:
                continue
            snapshot = analysis.metrics_snapshot or {}
            kpis = snapshot.get("kpis", {})
            points.append(
                HistoricalPoint(
                    upload_id=str(upload.id),
                    label=upload.label or upload.filename,
                    uploaded_at=upload.created_at.isoformat(),
                    row_count=upload.row_count,
                    late_shipment_pct=float(kpis.get("late_shipment_pct", 0.0)),
                    avg_delay_days=float(kpis.get("avg_delay_days", 0.0)),
                    delivery_success_rate=float(kpis.get("delivery_success_rate", 0.0)),
                    risk_score=float(analysis.risk_score),
                )
            )

        report = build_historical_report(points)
        await cache.cache_set(key, report.model_dump(mode="json"))
        return report

    # ── AI narration ───────────────────────────────────────────────────

    async def run_analysis(self, analysis_id: uuid.UUID) -> Analysis:
        """Compute metrics, ask Claude to explain them, persist the result.

        Called from the Celery worker. Failures are recorded on the row rather
        than raised, so the frontend can poll a terminal state either way.
        """
        analysis = await self.analyses.get(analysis_id)
        if analysis is None:
            raise NotFoundError("Analysis not found.")

        upload = await self.uploads.get(analysis.upload_id)
        if upload is None:
            raise NotFoundError("Upload not found.")

        analysis.status = AnalysisStatus.RUNNING
        await self.session.commit()

        try:
            report = await self.build_report(analysis.upload_id, use_cache=False)

            # Deterministic fields are written first and unconditionally: even
            # if the model call fails below, the dashboard has real numbers.
            analysis.risk_score = report.risk.score
            analysis.overall_risk = report.risk.level
            analysis.metrics_snapshot = report.model_dump(mode="json")
            analysis.healthy_signals = report.healthy_signals

            result = await self.claude.analyze(report)
            payload = result.payload

            analysis.summary = payload.summary
            if payload.healthy_signals:
                analysis.healthy_signals = payload.healthy_signals
            analysis.model_name = result.model
            analysis.input_tokens = result.input_tokens
            analysis.output_tokens = result.output_tokens
            analysis.duration_ms = result.duration_ms
            analysis.status = AnalysisStatus.COMPLETED
            analysis.error_message = None

            await self.analyses.replace_risks(
                analysis.id,
                [
                    Risk(
                        title=item.title,
                        risk_level=item.risk_level,
                        explanation=item.explanation,
                        recommendation=item.recommendation,
                        affected_items=item.affected_items,
                        evidence_metric=item.evidence_metric,
                    )
                    for item in payload.risks
                ],
            )

            upload.status = UploadStatus.COMPLETED
            upload.error_message = None

        except UpstreamServiceError as exc:
            # The model failed but the metrics did not — keep the numbers,
            # mark the narration as failed, and let the user retry.
            logger.warning("analysis_llm_failed", analysis_id=str(analysis_id), error=str(exc))
            analysis.status = AnalysisStatus.FAILED
            analysis.error_message = str(exc)
            upload.status = UploadStatus.COMPLETED
        except Exception as exc:
            logger.exception("analysis_failed", analysis_id=str(analysis_id))
            analysis.status = AnalysisStatus.FAILED
            analysis.error_message = f"Analysis failed: {exc}"
            upload.status = UploadStatus.FAILED
            upload.error_message = str(exc)

        await self.session.commit()
        # The user's history rollup now includes this upload.
        await cache.cache_delete(cache.history_key(str(upload.user_id)))

        logger.info("analysis_finished", analysis_id=str(analysis_id), status=analysis.status)
        return analysis

    async def compare_uploads(
        self, before_id: uuid.UUID, after_id: uuid.UUID, user_id: uuid.UUID
    ) -> tuple[AnalyticsReport, AnalyticsReport, dict]:
        """Diff two uploads. Ownership is checked on both sides."""
        for upload_id in (before_id, after_id):
            if await self.uploads.get_for_user(upload_id, user_id) is None:
                raise NotFoundError(f"Upload {upload_id} not found.")

        before = await self.build_report(before_id)
        after = await self.build_report(after_id)
        result = await self.claude.compare(before, after)
        return before, after, result.payload.model_dump()
