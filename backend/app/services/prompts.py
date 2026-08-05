"""Prompt construction.

Kept separate from the Claude client so prompts can be asserted on in unit
tests without any network access.

The governing rule: the model receives *computed metrics*, not raw rows, and is
told explicitly not to calculate anything. Every figure it cites must already
exist in the brief, which is what makes the output traceable.
"""

from __future__ import annotations

from app.schemas.analytics import AnalyticsReport, DimensionScore
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
6. Rank risks by business impact, most severe first.
7. The brief only contains sections the customer's file could support. A missing \
section means that data was not provided — never treat its absence as a good result, \
and never comment on a dimension that is not in the brief."""


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

    # Optional sections. Each is omitted when the upload lacked the columns for
    # it, which also keeps the model from commenting on dimensions this
    # customer never provided.
    lines += _dimension_lines("carriers", report.carriers, top_n)
    lines += _dimension_lines("transport_modes", report.transport_modes, top_n)
    lines += _dimension_lines("service_levels", report.service_levels, top_n)
    lines += _dimension_lines("product_categories", report.categories, top_n)
    # Lanes are deliberately NOT sent. A lane label embeds the destination,
    # which in real exports is routinely a customer name or a street address —
    # the one field in this model most likely to carry personal data. It is
    # computed locally and shown to the data's owner on the dashboard; that
    # does not justify sending it to a third-party API to slightly enrich a
    # narration. See tests/unit/test_security_and_prompts.py.
    if report.lanes:
        lines += ["", f"[lanes] {len(report.lanes)} routes analysed (labels withheld)"]

    if report.cost:
        c = report.cost
        lines += [
            "",
            f"[freight_cost] (covers {c.coverage_pct}% of rows)",
            f"total_freight_cost: {_fmt_money(c.total_freight_cost)}",
            f"avg_freight_cost: {_fmt_money(c.avg_freight_cost)}",
            f"freight_spent_on_late_shipments: {_fmt_money(c.freight_spent_on_late_shipments)}",
        ]
        if c.freight_pct_of_goods is not None:
            lines.append(f"freight_pct_of_goods: {c.freight_pct_of_goods}%")
        if c.freight_per_unit is not None:
            lines.append(f"freight_per_unit: {_fmt_money(c.freight_per_unit)}")

    if report.quality:
        q = report.quality
        lines += ["", "[quality]", f"perfect_order_rate_pct: {q.perfect_order_rate_pct}%"]
        if q.damage_rate_pct is not None:
            lines.append(f"damage_rate_pct: {q.damage_rate_pct}% ({q.damaged_count} shipments)")
        if q.return_rate_pct is not None:
            lines.append(f"return_rate_pct: {q.return_rate_pct}% ({q.returned_count} shipments)")
        if q.avg_fill_rate_pct is not None:
            lines.append(f"avg_fill_rate_pct: {q.avg_fill_rate_pct}%")

    if report.emissions:
        e = report.emissions
        lines += [
            "",
            f"[emissions] (covers {e.coverage_pct}% of rows)",
            f"total_co2_kg: {e.total_co2_kg}",
            f"avg_co2_per_shipment_kg: {e.avg_co2_per_shipment_kg}",
        ]
        if e.co2_by_mode_kg:
            by_mode = ", ".join(f"{mode}={kg}kg" for mode, kg in e.co2_by_mode_kg.items())
            lines.append(f"co2_by_mode_kg: {by_mode}")

    if report.healthy_signals:
        lines += ["", "[computed_healthy_signals]"]
        lines += [f"  - {signal}" for signal in report.healthy_signals]

    if report.available_dimensions:
        # Naming what the file *did* carry stops the model inferring that an
        # absent section means a clean result.
        lines += ["", f"[dimensions_present] {', '.join(report.available_dimensions)}"]

    return "\n".join(lines)


def _dimension_lines(name: str, scores: list[DimensionScore], top_n: int) -> list[str]:
    if not scores:
        return []
    lines = ["", f"[{name}] worst {min(top_n, len(scores))} by late rate"]
    for score in scores[:top_n]:
        parts = [
            f"  {score.label}: n={score.shipment_count} ({score.share_pct}% of volume)",
            f"late={score.late_pct}%",
            f"avg_delay={score.avg_delay_days}d",
        ]
        if score.avg_freight_cost is not None:
            parts.append(f"avg_freight={_fmt_money(score.avg_freight_cost)}")
        lines.append(", ".join(parts))
    return lines


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
