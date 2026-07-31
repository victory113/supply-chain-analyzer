"""Retrieval-grounded Q&A over the user's stored supply chain data.

This is RAG over *structured* business data rather than documents: instead of
embedding prose, we retrieve the relevant slices of the computed analytics
(KPIs, vendor scores, country risk, trend series, prior analyses) and put only
those in the prompt. Retrieval is keyword-routed, which for a fixed, small set
of metric families is both cheaper and more predictable than a vector search.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.repositories.analysis import AnalysisRepository
from app.repositories.upload import UploadRepository
from app.schemas.analytics import AnalyticsReport
from app.schemas.chat import ChatRequest, ChatResponse, ChatSource
from app.services.analysis import AnalysisService
from app.services.claude import ClaudeService

logger = get_logger(__name__)

# Question keywords -> which metric families to retrieve.
INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "vendors": ("vendor", "supplier", "manufacturer", "who", "worst", "best", "partner"),
    "countries": ("country", "region", "origin", "geographic", "where", "china", "import"),
    "trend": (
        "trend",
        "over time",
        "increasing",
        "rising",
        "falling",
        "month",
        "year",
        "changed",
        "changing",
        "why",
        "worse",
        "better",
    ),
    "risk": ("risk", "score", "exposure", "danger", "critical", "concern"),
    "analysis": ("recommend", "should", "advice", "fix", "mitigate", "action", "do"),
}

# When nothing matches, these give a useful general answer.
DEFAULT_SECTIONS = ("kpis", "risk", "vendors")

# Cap how many datasets go into one prompt — beyond this the context is mostly
# noise and the token cost stops paying for itself.
MAX_UPLOADS_IN_CONTEXT = 6


def route_intent(question: str) -> set[str]:
    """Pick which metric families are relevant to the question."""
    lowered = question.lower()
    sections = {
        section
        for section, keywords in INTENT_KEYWORDS.items()
        if any(keyword in lowered for keyword in keywords)
    }
    sections.update(DEFAULT_SECTIONS[:2])  # KPIs and risk are always useful context
    return sections or set(DEFAULT_SECTIONS)


class ChatService:
    def __init__(self, session: AsyncSession, *, claude: ClaudeService | None = None) -> None:
        self.session = session
        self.uploads = UploadRepository(session)
        self.analyses = AnalysisRepository(session)
        self.claude = claude or ClaudeService()
        self.analysis_service = AnalysisService(session, claude=self.claude)

    async def ask(self, request: ChatRequest, user_id: uuid.UUID) -> ChatResponse:
        sections = route_intent(request.question)
        reports = await self._retrieve(request.upload_id, user_id)

        if not reports:
            raise NotFoundError("No analysed uploads found. Upload a CSV before asking questions.")

        context_parts: list[str] = []
        sources: list[ChatSource] = []

        for label, report in reports:
            block, block_sources = self._render(label, report, sections)
            context_parts.append(block)
            sources.extend(block_sources)

        result = await self.claude.answer_question(
            request.question,
            "\n\n".join(context_parts),
            uploads_considered=len(reports),
            history=[turn.model_dump() for turn in request.history],
        )

        logger.info(
            "chat_answered",
            user_id=str(user_id),
            uploads=len(reports),
            sections=sorted(sections),
            input_tokens=result.input_tokens,
        )

        return ChatResponse(
            answer=result.payload,
            sources=sources,
            uploads_considered=len(reports),
        )

    async def _retrieve(
        self, upload_id: uuid.UUID | None, user_id: uuid.UUID
    ) -> list[tuple[str, AnalyticsReport]]:
        """Fetch the analytics reports the question should be answered from."""
        if upload_id is not None:
            upload = await self.uploads.get_for_user(upload_id, user_id)
            if upload is None:
                raise NotFoundError("Upload not found.")
            report = await self.analysis_service.build_report(upload.id)
            return [(upload.label or upload.filename, report)]

        # No scope given: use the most recent datasets, newest first.
        uploads = await self.uploads.list_for_user(user_id, limit=MAX_UPLOADS_IN_CONTEXT)
        reports: list[tuple[str, AnalyticsReport]] = []
        for upload in uploads:
            analysis = await self.analyses.latest_for_upload(upload.id)
            if analysis is None or not analysis.metrics_snapshot:
                continue
            reports.append(
                (
                    upload.label or upload.filename,
                    AnalyticsReport.model_validate(analysis.metrics_snapshot),
                )
            )
        return reports

    @staticmethod
    def _render(
        label: str, report: AnalyticsReport, sections: set[str]
    ) -> tuple[str, list[ChatSource]]:
        """Render only the requested sections, and record what was included."""
        lines = [f"--- DATASET: {label} ---"]
        sources: list[ChatSource] = []
        k = report.kpis

        # KPIs anchor every answer, so they are included unconditionally.
        lines += [
            "[kpis]",
            f"shipments={k.total_shipments}, late={k.late_shipment_pct}%, "
            f"avg_delay={k.avg_delay_days}d, p90_delay={k.p90_delay_days}d, "
            f"success_rate={k.delivery_success_rate}%, "
            f"value_at_risk=${k.value_at_risk:,.0f}",
        ]
        sources.append(
            ChatSource(
                kind="kpi",
                reference=f"{label} / kpis",
                detail=f"{k.total_shipments} shipments, {k.late_shipment_pct}% late",
            )
        )

        if "risk" in sections:
            lines += [
                "[risk]",
                f"composite={report.risk.score}/100 ({report.risk.level.value})",
                f"components={report.risk.components}",
            ]
            sources.append(
                ChatSource(
                    kind="risk",
                    reference=f"{label} / risk",
                    detail=f"composite score {report.risk.score}",
                )
            )

        if "vendors" in sections and report.vendors:
            lines.append("[vendors] worst-first")
            for vendor in report.vendors[:5]:
                lines.append(
                    f"  {vendor.vendor}: health={vendor.health_score}, "
                    f"late={vendor.late_pct}%, avg_delay={vendor.avg_delay_days}d, "
                    f"shipments={vendor.shipment_count}"
                )
            sources.append(
                ChatSource(
                    kind="vendor",
                    reference=f"{label} / vendors",
                    detail=f"{len(report.vendors)} vendors scored",
                )
            )

        if "countries" in sections and report.countries:
            lines.append("[countries] riskiest-first")
            for country in report.countries[:5]:
                lines.append(
                    f"  {country.country}: risk={country.risk_score}, "
                    f"late={country.late_pct}%, shipments={country.shipment_count}"
                )
            sources.append(
                ChatSource(
                    kind="country",
                    reference=f"{label} / countries",
                    detail=f"{len(report.countries)} origin countries",
                )
            )

        if "trend" in sections:
            lines += [
                "[trend]",
                f"direction={report.trend.direction}; {report.trend.commentary}",
            ]
            for point in report.trend.points[-6:]:
                lines.append(
                    f"  {point.period}: n={point.shipment_count}, "
                    f"late={point.late_pct}%, delay={point.avg_delay_days}d"
                )
            sources.append(
                ChatSource(
                    kind="trend",
                    reference=f"{label} / trend",
                    detail=report.trend.direction,
                )
            )

        return "\n".join(lines), sources
