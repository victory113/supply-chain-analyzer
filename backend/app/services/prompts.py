"""Prompt construction.

Kept separate from the Claude client so prompts can be asserted on in unit
tests without any network access.

The governing rule: the model receives *computed metrics*, not raw rows, and is
told explicitly not to calculate anything. Every figure it cites must already
exist in the brief, which is what makes the output traceable.
"""

from __future__ import annotations

from app.schemas.analytics import AnalyticsReport
from app.services.analytics.risk import describe_drivers

SYSTEM_PROMPT = """You are a supply chain risk analyst writing for a non-technical \
operations executive.

You will be given a METRICS BRIEF that has already been computed from the \
customer's data by a deterministic analytics engine.

Rules:
1. Never compute, estimate, or invent a number. Every figure you cite must appear \
verbatim in the brief.
2. If the brief does not support a claim, do not make it.
3. Each risk must set `evidence_metric` to the name of the brief field it rests on \
(for example `kpis.late_shipment_pct` or `vendors[0].health_score`).
4. Write explanations in two sentences or fewer, in plain English, with no jargon.
5. Each recommendation must be a concrete action someone could take this week — \
not "monitor the situation".
6. Rank risks by business impact, most severe first."""


def _fmt_money(value: float) -> str:
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:.0f}"


def build_metrics_brief(report: AnalyticsReport, *, top_n: int = 5) -> str:
    """Render the analytics report as a compact, token-efficient brief."""
    k = report.kpis
    lines: list[str] = [
        "=== METRICS BRIEF ===",
        "",
        "[kpis]",
        f"total_shipments: {k.total_shipments}",
        f"late_shipments: {k.late_shipments}",
        f"late_shipment_pct: {k.late_shipment_pct}%",
        f"avg_delay_days: {k.avg_delay_days}",
        f"avg_delay_days_when_late: {k.avg_delay_days_when_late}",
        f"median_delay_days: {k.median_delay_days}",
        f"p90_delay_days: {k.p90_delay_days}",
        f"avg_lead_time_days: {k.avg_lead_time_days}",
        f"delivery_success_rate: {k.delivery_success_rate}%",
        f"total_value: {_fmt_money(k.total_value)}",
        f"value_at_risk: {_fmt_money(k.value_at_risk)}",
        f"distinct_vendors: {k.distinct_vendors}",
        f"distinct_countries: {k.distinct_countries}",
        "",
        "[risk]",
        f"composite_score: {report.risk.score}/100 ({report.risk.level.value})",
        "top_drivers:",
    ]
    lines += [f"  - {driver}" for driver in describe_drivers(report.risk)]

    lines += ["", f"[vendors] worst {min(top_n, len(report.vendors))} by health score"]
    for vendor in report.vendors[:top_n]:
        lines.append(
            f"  {vendor.vendor}: health={vendor.health_score}/100 "
            f"({vendor.risk_level.value}), shipments={vendor.shipment_count}, "
            f"late={vendor.late_pct}%, avg_delay={vendor.avg_delay_days}d, "
            f"value_at_risk={_fmt_money(vendor.value_at_risk)}"
        )

    lines += ["", f"[countries] riskiest {min(top_n, len(report.countries))} origins"]
    for country in report.countries[:top_n]:
        lines.append(
            f"  {country.country}: risk={country.risk_score}/100 "
            f"({country.risk_level.value}), shipments={country.shipment_count}, "
            f"late={country.late_pct}%, avg_delay={country.avg_delay_days}d"
        )

    lines += [
        "",
        "[trend]",
        f"direction: {report.trend.direction}",
        f"commentary: {report.trend.commentary}",
    ]
    if report.trend.points:
        lines.append("monthly (period, shipments, late%, avg_delay):")
        # Last 12 periods only — older history rarely changes the read and costs
        # tokens on every request.
        for point in report.trend.points[-12:]:
            lines.append(
                f"  {point.period}: n={point.shipment_count}, "
                f"late={point.late_pct}%, delay={point.avg_delay_days}d"
            )

    if report.healthy_signals:
        lines += ["", "[computed_healthy_signals]"]
        lines += [f"  - {signal}" for signal in report.healthy_signals]

    return "\n".join(lines)


def build_analysis_prompt(report: AnalyticsReport) -> str:
    return f"""{build_metrics_brief(report)}

=== TASK ===
Using only the brief above:
1. Write a one-sentence overall assessment for `summary`.
2. Identify the top 3 risks. For each, give a title, a risk_level, a plain-English \
explanation, a concrete recommendation, the affected vendors/countries/products, and \
the `evidence_metric` field name it is based on.
3. List up to 4 `healthy_signals` — things that are demonstrably working. You may \
reuse or rephrase the computed signals."""


def build_comparison_prompt(before: AnalyticsReport, after: AnalyticsReport) -> str:
    return f"""Two metrics briefs from the same supply chain at different points in time.

=== BEFORE ===
{build_metrics_brief(before, top_n=3)}

=== AFTER ===
{build_metrics_brief(after, top_n=3)}

=== TASK ===
Identify what changed. Classify each change as IMPROVED, WORSENED, or NEW_ISSUE, \
citing the specific metric that moved and by how much. Set `net_change` to IMPROVED, \
WORSENED, or MIXED. Do not compute new figures — only compare numbers present above."""


def build_chat_prompt(question: str, context: str, uploads_considered: int) -> str:
    return f"""You are answering a question about a customer's stored supply chain data.

=== AVAILABLE DATA ({uploads_considered} dataset(s)) ===
{context}

=== QUESTION ===
{question}

=== TASK ===
Answer using only the data above. Cite the specific metrics that support your answer. \
If the data cannot answer the question, say so plainly and name what would be needed \
— do not speculate."""
