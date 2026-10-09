"""Tools the chat agent can call.

This is the retrieval layer for the assistant, and it replaces a keyword
router. Previously the server guessed which metrics a question needed by
matching words in it; now the model is given a set of tools and decides for
itself what to fetch, over as many steps as the question takes. "Which vendor
is worst, and has that changed since last quarter?" becomes a vendor lookup
followed by a trend lookup, chosen by the model rather than by a word list.

Two properties matter more than the tool list itself:

* **Tenancy is enforced here, not in the prompt.** Every handler resolves data
  through the repositories scoped to one ``user_id``. The model supplies a
  dataset *name*, never an ID it could invent, and a name that doesn't belong
  to this user simply doesn't resolve. A hallucinated argument cannot reach
  another tenant's rows.
* **Tools return computed metrics, never raw shipments.** Same boundary the
  rest of the system keeps: the model reasons over aggregates it did not
  calculate, so an answer can always be traced to a figure in the report.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.repositories.analysis import AnalysisRepository
from app.repositories.upload import UploadRepository
from app.schemas.analytics import AnalyticsReport
from app.services.analysis import AnalysisService
from app.services.analytics.risk import WEIGHTS as RISK_WEIGHTS

logger = get_logger(__name__)

# Beyond this the model is choosing between datasets it can't meaningfully
# distinguish, and every listing costs tokens.
MAX_DATASETS = 12
# Row caps per tool call. The model can ask for fewer; it cannot ask for the
# whole table, because a long tail of near-identical rows is noise that
# crowds out the rows that matter.
DEFAULT_ROWS = 5
MAX_ROWS = 15

DIMENSIONS = ("carriers", "transport_modes", "service_levels", "categories", "lanes")


@dataclass
class ToolCall:
    """One executed tool call, recorded so the answer stays auditable."""

    name: str
    arguments: dict[str, Any]
    ok: bool = True
    summary: str = ""


@dataclass
class AgentToolset:
    """Tools bound to a single user's data for the life of one question."""

    session: AsyncSession
    user_id: uuid.UUID
    upload_id: uuid.UUID | None = None
    calls: list[ToolCall] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.uploads = UploadRepository(self.session)
        self.analyses = AnalysisRepository(self.session)
        self.analysis_service = AnalysisService(self.session)
        # Resolved reports are reused across tool calls within one question:
        # the model will usually ask about the same dataset several times.
        self._reports: dict[str, tuple[str, AnalyticsReport]] = {}

    # ── Schema handed to the model ────────────────────────────────────

    def definitions(self) -> list[dict[str, Any]]:
        """The tool list in the shape the Messages API expects.

        Descriptions are written for the model, not for a developer: they say
        when to reach for the tool, because that is the decision it is making.
        """
        dataset_arg = {
            "type": "string",
            "description": (
                "Name of the dataset, exactly as returned by list_datasets. "
                "Omit to use the most recently uploaded one."
            ),
        }
        limit_arg = {
            "type": "integer",
            "description": f"How many rows to return (1-{MAX_ROWS}).",
        }

        return [
            {
                "name": "list_datasets",
                "description": (
                    "List the user's analysed datasets with their row counts and upload "
                    "dates. Call this first when the question mentions a specific "
                    "dataset, compares datasets, or asks about change over time."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "get_kpis",
                "description": (
                    "Headline metrics for one dataset: shipment count, late percentage, "
                    "average and p90 delay, delivery success rate, total value and value "
                    "at risk. Use for any 'how are we doing overall' question."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {"dataset": dataset_arg},
                },
            },
            {
                "name": "get_vendor_scores",
                "description": (
                    "Vendor health scores, worst first, with late rate, average delay, "
                    "shipment count and value at risk. Use for questions about "
                    "suppliers, vendors or manufacturers, or 'who is the problem'."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {"dataset": dataset_arg, "limit": limit_arg},
                },
            },
            {
                "name": "get_country_risk",
                "description": (
                    "Risk score per origin country, riskiest first. Use for questions "
                    "about geography, origins, regions or sourcing locations."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {"dataset": dataset_arg, "limit": limit_arg},
                },
            },
            {
                "name": "get_trend",
                "description": (
                    "Month-by-month delay and volume for one dataset, plus the computed "
                    "direction (improving, worsening, stable). Use for questions about "
                    "change, timing, seasonality or 'is it getting worse'."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {"dataset": dataset_arg},
                },
            },
            {
                "name": "get_risk_breakdown",
                "description": (
                    "The composite risk score with the weighted components behind it. "
                    "Use when asked why the score is what it is, or what is driving risk."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {"dataset": dataset_arg},
                },
            },
            {
                "name": "get_dimension",
                "description": (
                    "Performance broken down by carrier, transport mode, service level, "
                    "product category or trade lane. Returns an empty result when the "
                    "upload did not contain that column, which means the question cannot "
                    "be answered from this data — say so rather than guessing."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "dimension": {
                            "type": "string",
                            "enum": list(DIMENSIONS),
                            "description": "Which breakdown to fetch.",
                        },
                        "dataset": dataset_arg,
                        "limit": limit_arg,
                    },
                    "required": ["dimension"],
                },
            },
            {
                "name": "get_operations_summary",
                "description": (
                    "Freight cost economics, order quality (damage, returns, fill rate) "
                    "and carbon emissions for one dataset. Any of the three may be "
                    "absent if the upload lacked those columns."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {"dataset": dataset_arg},
                },
            },
            {
                "name": "get_history",
                "description": (
                    "Risk and delay figures across ALL of the user's uploads over time, "
                    "for comparing one dataset against another or seeing a long-run "
                    "direction. Use when the question spans more than one dataset."
                ),
                "input_schema": {"type": "object", "properties": {}},
            },
        ]

    # ── Dispatch ──────────────────────────────────────────────────────

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run one tool and record it. Never raises — errors come back as data.

        A tool that raises would end the conversation; a tool that *reports* a
        problem lets the model recover, usually by calling list_datasets and
        trying again with a real name.
        """
        handler = self._handlers().get(name)
        if handler is None:
            self.calls.append(
                ToolCall(name=name, arguments=arguments, ok=False, summary="unknown tool")
            )
            return {"error": f"No tool named {name!r}."}

        try:
            result = await handler(arguments)
        except LookupError as exc:
            self.calls.append(ToolCall(name=name, arguments=arguments, ok=False, summary=str(exc)))
            return {"error": str(exc)}
        except Exception as exc:  # surfaced to the model as data, not raised
            logger.exception("agent_tool_failed", tool=name)
            self.calls.append(
                ToolCall(name=name, arguments=arguments, ok=False, summary="internal error")
            )
            return {"error": f"The {name} tool failed: {exc}"}

        self.calls.append(
            ToolCall(
                name=name,
                arguments=arguments,
                ok=True,
                summary=_describe(name, result),
            )
        )
        return result

    def datasets_touched(self) -> set[str]:
        """Distinct dataset labels actually read while answering."""
        return {label for label, _ in self._reports.values()}

    def _handlers(self) -> dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]]:
        return {
            "list_datasets": self._list_datasets,
            "get_kpis": self._get_kpis,
            "get_vendor_scores": self._get_vendor_scores,
            "get_country_risk": self._get_country_risk,
            "get_trend": self._get_trend,
            "get_risk_breakdown": self._get_risk_breakdown,
            "get_dimension": self._get_dimension,
            "get_operations_summary": self._get_operations_summary,
            "get_history": self._get_history,
        }

    # ── Handlers ──────────────────────────────────────────────────────

    async def _list_datasets(self, _: dict[str, Any]) -> dict[str, Any]:
        uploads = await self.uploads.list_for_user(self.user_id, limit=MAX_DATASETS)
        return {
            "datasets": [
                {
                    "name": upload.label or upload.filename,
                    "rows": upload.row_count,
                    "uploaded": upload.created_at.date().isoformat(),
                    "status": str(upload.status),
                }
                for upload in uploads
            ]
        }

    async def _get_kpis(self, args: dict[str, Any]) -> dict[str, Any]:
        name, report = await self._resolve(args.get("dataset"))
        k = report.kpis
        return {
            "dataset": name,
            "total_shipments": k.total_shipments,
            "late_shipments": k.late_shipments,
            "late_shipment_pct": k.late_shipment_pct,
            "avg_delay_days": k.avg_delay_days,
            "avg_delay_days_when_late": k.avg_delay_days_when_late,
            "p90_delay_days": k.p90_delay_days,
            "delivery_success_rate": k.delivery_success_rate,
            "total_value": k.total_value,
            "value_at_risk": k.value_at_risk,
            "distinct_vendors": k.distinct_vendors,
            "distinct_countries": k.distinct_countries,
        }

    async def _get_vendor_scores(self, args: dict[str, Any]) -> dict[str, Any]:
        name, report = await self._resolve(args.get("dataset"))
        limit = _clamp_limit(args.get("limit"))
        return {
            "dataset": name,
            "vendors_scored": len(report.vendors),
            "vendors": [
                {
                    "vendor": v.vendor,
                    "health_score": v.health_score,
                    "risk_level": v.risk_level.value,
                    "late_pct": v.late_pct,
                    "avg_delay_days": v.avg_delay_days,
                    "shipment_count": v.shipment_count,
                    "value_at_risk": v.value_at_risk,
                }
                for v in report.vendors[:limit]
            ],
        }

    async def _get_country_risk(self, args: dict[str, Any]) -> dict[str, Any]:
        name, report = await self._resolve(args.get("dataset"))
        limit = _clamp_limit(args.get("limit"))
        return {
            "dataset": name,
            "countries": [
                {
                    "country": c.country,
                    "risk_score": c.risk_score,
                    "risk_level": c.risk_level.value,
                    "late_pct": c.late_pct,
                    "avg_delay_days": c.avg_delay_days,
                    "shipment_count": c.shipment_count,
                }
                for c in report.countries[:limit]
            ],
        }

    async def _get_trend(self, args: dict[str, Any]) -> dict[str, Any]:
        name, report = await self._resolve(args.get("dataset"))
        return {
            "dataset": name,
            "direction": report.trend.direction,
            "commentary": report.trend.commentary,
            "delay_change_pct": report.trend.delay_change_pct,
            "months": [
                {
                    "period": p.period,
                    "shipments": p.shipment_count,
                    "late_pct": p.late_pct,
                    "avg_delay_days": p.avg_delay_days,
                }
                for p in report.trend.points[-12:]
            ],
        }

    async def _get_risk_breakdown(self, args: dict[str, Any]) -> dict[str, Any]:
        name, report = await self._resolve(args.get("dataset"))
        return {
            "dataset": name,
            "score": report.risk.score,
            "level": report.risk.level.value,
            "components": report.risk.components,
            "weights": report.risk.weights,
            # Compared against the *canonical* weight list, not the returned
            # one: an unmeasurable component is dropped from both `components`
            # and `weights` (the rest are renormalised), so comparing those two
            # to each other can only ever produce an empty set.
            "components_not_measurable": sorted(set(RISK_WEIGHTS) - set(report.risk.components)),
        }

    async def _get_dimension(self, args: dict[str, Any]) -> dict[str, Any]:
        dimension = str(args.get("dimension", "")).strip()
        if dimension not in DIMENSIONS:
            raise LookupError(
                f"Unknown dimension {dimension!r}. Choose one of: {', '.join(DIMENSIONS)}."
            )

        name, report = await self._resolve(args.get("dataset"))
        limit = _clamp_limit(args.get("limit"))
        rows = getattr(report, dimension, []) or []

        if not rows:
            return {
                "dataset": name,
                "dimension": dimension,
                "rows": [],
                "note": (
                    f"This dataset has no {dimension} data - the uploaded file did not "
                    "contain that column. The question cannot be answered from it."
                ),
            }

        return {
            "dataset": name,
            "dimension": dimension,
            "rows": [
                {
                    "label": r.label,
                    "share_pct": r.share_pct,
                    "shipment_count": r.shipment_count,
                    "late_pct": r.late_pct,
                    "avg_delay_days": r.avg_delay_days,
                    "avg_freight_cost": r.avg_freight_cost,
                }
                for r in rows[:limit]
            ],
        }

    async def _get_operations_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        name, report = await self._resolve(args.get("dataset"))
        return {
            "dataset": name,
            "cost": report.cost.model_dump() if report.cost else None,
            "quality": report.quality.model_dump() if report.quality else None,
            "emissions": report.emissions.model_dump() if report.emissions else None,
            "available_dimensions": report.available_dimensions,
        }

    async def _get_history(self, _: dict[str, Any]) -> dict[str, Any]:
        history = await self.analysis_service.build_history(self.user_id)
        return {
            "direction": history.direction,
            "summary": history.summary,
            "points": [
                {
                    "dataset": p.label,
                    "uploaded": p.uploaded_at,
                    "rows": p.row_count,
                    "risk_score": p.risk_score,
                    "late_shipment_pct": p.late_shipment_pct,
                    "avg_delay_days": p.avg_delay_days,
                }
                for p in history.points
            ],
        }

    # ── Dataset resolution ────────────────────────────────────────────

    async def _resolve(self, requested: str | None) -> tuple[str, AnalyticsReport]:
        """Turn a dataset *name* from the model into a report it may read.

        Names are matched only against this user's own uploads, which is what
        makes an invented argument harmless rather than dangerous.
        """
        key = (requested or "").strip().lower()
        if key in self._reports:
            return self._reports[key]

        uploads = await self.uploads.list_for_user(self.user_id, limit=MAX_DATASETS)
        if not uploads:
            raise LookupError("This account has no uploaded datasets yet.")

        # A question scoped to one upload in the UI pins every tool to it,
        # regardless of what the model asks for.
        if self.upload_id is not None:
            match = next((u for u in uploads if u.id == self.upload_id), None)
            if match is None:
                raise LookupError("The selected dataset is no longer available.")
        elif not key:
            match = uploads[0]  # most recent
        else:
            match = next(
                (u for u in uploads if (u.label or u.filename).strip().lower() == key), None
            )
            if match is None:
                # Substring fallback: the model often shortens a filename.
                match = next(
                    (u for u in uploads if key in (u.label or u.filename).strip().lower()), None
                )
            if match is None:
                available = ", ".join(u.label or u.filename for u in uploads)
                raise LookupError(
                    f"No dataset named {requested!r}. Available datasets: {available}."
                )

        label = match.label or match.filename
        analysis = await self.analyses.latest_for_upload(match.id)
        if analysis is not None and analysis.metrics_snapshot:
            report = AnalyticsReport.model_validate(analysis.metrics_snapshot)
        else:
            # No stored snapshot (analysis still queued, or it failed before
            # the model call) — recompute, which is deterministic anyway.
            report = await self.analysis_service.build_report(match.id)

        resolved = (label, report)
        self._reports[key] = resolved
        self._reports[label.lower()] = resolved
        return resolved


def _clamp_limit(value: Any) -> int:
    try:
        requested = int(value)
    except (TypeError, ValueError):
        return DEFAULT_ROWS
    return max(1, min(requested, MAX_ROWS))


def _describe(name: str, result: dict[str, Any]) -> str:
    """One line per call for the audit trail shown to the user."""
    if name == "list_datasets":
        return f"{len(result.get('datasets', []))} dataset(s)"
    if name == "get_vendor_scores":
        return f"{len(result.get('vendors', []))} vendor(s)"
    if name == "get_country_risk":
        return f"{len(result.get('countries', []))} country(ies)"
    if name == "get_trend":
        return f"{result.get('direction', 'unknown')}, {len(result.get('months', []))} month(s)"
    if name == "get_dimension":
        rows = result.get("rows", [])
        return f"{result.get('dimension')}: {len(rows)} row(s)" if rows else "no data for that"
    if name == "get_risk_breakdown":
        return f"score {result.get('score')}"
    if name == "get_kpis":
        return f"{result.get('total_shipments')} shipments"
    if name == "get_history":
        return f"{len(result.get('points', []))} upload(s)"
    return "ok"
