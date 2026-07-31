"""Service-level tests for the analysis pipeline, with Claude stubbed."""

from __future__ import annotations

from app.core.exceptions import UpstreamServiceError
from app.core.security import hash_password
from app.models.enums import AnalysisStatus, UploadStatus
from app.models.user import User
from app.services.analysis import AnalysisService

CSV = b"""shipment_id,vendor,origin_country,quantity,unit_cost,lead_time_days,status,delay_days,shipped_on
S001,GlobalParts,China,500,45.00,14,delayed,8,2024-01-15
S002,FastShip,Brazil,1200,12.50,7,on_time,0,2024-02-15
S003,GlobalParts,Taiwan,250,120.00,21,delayed,15,2024-03-14
S004,QuickSupply,Mexico,3000,2.10,3,on_time,0,2024-04-15
"""


async def make_user(session) -> User:
    user = User(email="analyst@example.com", password_hash=hash_password("sup3r-secret-pw"))
    session.add(user)
    await session.flush()
    return user


class TestUploadPipeline:
    async def test_create_upload_persists_rows_and_queues_an_analysis(self, session, fake_claude):
        user = await make_user(session)
        service = AnalysisService(session, claude=fake_claude)

        upload, analysis, result = await service.create_upload(
            user_id=user.id, filename="data.csv", content=CSV
        )

        assert upload.row_count == 4
        assert upload.status == UploadStatus.ANALYZING
        assert analysis.status == AnalysisStatus.QUEUED
        assert result.report.detected_columns["vendor"] == "vendor"

    async def test_non_csv_filename_is_rejected_before_any_work(self, session, fake_claude):
        import pytest

        from app.core.exceptions import ValidationError

        user = await make_user(session)
        service = AnalysisService(session, claude=fake_claude)

        with pytest.raises(ValidationError):
            await service.create_upload(user_id=user.id, filename="data.txt", content=CSV)


class TestRunAnalysis:
    async def test_successful_run_persists_metrics_and_narration(self, session, fake_claude):
        user = await make_user(session)
        service = AnalysisService(session, claude=fake_claude)
        _, analysis, _ = await service.create_upload(
            user_id=user.id, filename="data.csv", content=CSV
        )

        result = await service.run_analysis(analysis.id)

        assert result.status == AnalysisStatus.COMPLETED
        assert result.summary
        assert result.risk_score is not None
        assert result.metrics_snapshot is not None
        assert result.model_name == "claude-opus-5"

        refreshed = await service.analyses.get_with_risks(analysis.id)
        assert refreshed is not None
        assert [r.title for r in refreshed.risks] == ["Vendor concentration"]
        # Grounding: the model was asked to cite a computed metric, and did.
        assert refreshed.risks[0].evidence_metric == "vendors[0].health_score"

    async def test_prompt_is_built_from_computed_metrics(self, session, fake_claude):
        user = await make_user(session)
        service = AnalysisService(session, claude=fake_claude)
        _, analysis, _ = await service.create_upload(
            user_id=user.id, filename="data.csv", content=CSV
        )
        await service.run_analysis(analysis.id)

        prompt = fake_claude.calls[0]
        assert "METRICS BRIEF" in prompt
        assert "late_shipment_pct: 50.0%" in prompt
        assert "GlobalParts" in prompt

    async def test_model_failure_keeps_the_computed_metrics(self, session, fake_claude):
        """The dashboard must survive an LLM outage."""

        class BrokenClaude:
            async def analyze(self, report):
                raise UpstreamServiceError("Model unavailable")

        user = await make_user(session)
        service = AnalysisService(session, claude=BrokenClaude())
        _, analysis, _ = await service.create_upload(
            user_id=user.id, filename="data.csv", content=CSV
        )

        result = await service.run_analysis(analysis.id)

        assert result.status == AnalysisStatus.FAILED
        assert result.error_message
        # Deterministic values were written before the model call, so they stand.
        assert result.risk_score is not None
        assert result.metrics_snapshot is not None
        # The upload itself is still usable.
        upload = await service.uploads.get(result.upload_id)
        assert upload is not None and upload.status == UploadStatus.COMPLETED


class TestAnalyticsAndHistory:
    async def test_report_matches_the_uploaded_rows(self, session, fake_claude):
        user = await make_user(session)
        service = AnalysisService(session, claude=fake_claude)
        upload, _, _ = await service.create_upload(
            user_id=user.id, filename="data.csv", content=CSV
        )

        report = await service.build_report(upload.id, use_cache=False)

        assert report.kpis.total_shipments == 4
        assert report.kpis.late_shipment_pct == 50.0
        assert report.vendors[0].vendor == "GlobalParts"

    async def test_history_needs_at_least_two_analysed_uploads(self, session, fake_claude):
        user = await make_user(session)
        service = AnalysisService(session, claude=fake_claude)
        _, analysis, _ = await service.create_upload(
            user_id=user.id, filename="one.csv", content=CSV
        )
        await service.run_analysis(analysis.id)

        history = await service.build_history(user.id)
        assert history.direction == "insufficient_data"

    async def test_history_reports_a_direction_once_there_are_two(self, session, fake_claude):
        user = await make_user(session)
        service = AnalysisService(session, claude=fake_claude)

        for name in ("q1.csv", "q2.csv"):
            _, analysis, _ = await service.create_upload(
                user_id=user.id, filename=name, content=CSV
            )
            await service.run_analysis(analysis.id)

        history = await service.build_history(user.id)
        assert len(history.points) == 2
        assert history.direction in {"improving", "worsening", "stable"}
