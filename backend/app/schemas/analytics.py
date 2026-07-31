"""Analytics schemas.

These describe the output of the deterministic Python analytics engine — no
LLM is involved in producing any of these numbers.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.enums import RiskLevel


class KpiSummary(BaseModel):
    total_shipments: int
    late_shipments: int
    late_shipment_pct: float = Field(description="Share of shipments with delay_days > 0")
    avg_delay_days: float = Field(description="Mean delay across ALL shipments")
    avg_delay_days_when_late: float = Field(description="Mean delay across late ones only")
    median_delay_days: float
    p90_delay_days: float = Field(description="90th percentile delay — tail risk")
    avg_lead_time_days: float
    delivery_success_rate: float = Field(description="Share not delayed/critical/cancelled")
    total_value: float
    value_at_risk: float = Field(description="Value of shipments that are late or critical")
    distinct_vendors: int
    distinct_countries: int


class VendorScore(BaseModel):
    vendor: str
    shipment_count: int
    late_count: int
    late_pct: float
    avg_delay_days: float
    avg_lead_time_days: float
    total_value: float
    value_at_risk: float
    # 0 (worst) to 100 (best) — a weighted blend, see analytics/vendors.py
    health_score: float
    risk_level: RiskLevel


class CountryRisk(BaseModel):
    country: str
    shipment_count: int
    late_count: int
    late_pct: float
    avg_delay_days: float
    total_value: float
    risk_score: float
    risk_level: RiskLevel


class TrendPoint(BaseModel):
    period: str = Field(description="ISO month, e.g. 2024-01")
    shipment_count: int
    late_count: int
    late_pct: float
    avg_delay_days: float
    total_value: float


class TrendAnalysis(BaseModel):
    points: list[TrendPoint]
    direction: str = Field(description="improving | worsening | stable | insufficient_data")
    delay_change_pct: float | None = Field(
        default=None, description="Change in avg delay, first half vs second half"
    )
    commentary: str


class RiskBreakdown(BaseModel):
    """The composite score and its weighted inputs, so the number is explainable."""

    score: float
    level: RiskLevel
    components: dict[str, float]
    weights: dict[str, float]


class AnalyticsReport(BaseModel):
    upload_id: str
    kpis: KpiSummary
    vendors: list[VendorScore]
    countries: list[CountryRisk]
    trend: TrendAnalysis
    risk: RiskBreakdown
    healthy_signals: list[str]


class HistoricalPoint(BaseModel):
    upload_id: str
    label: str | None
    uploaded_at: str
    row_count: int
    late_shipment_pct: float
    avg_delay_days: float
    delivery_success_rate: float
    risk_score: float


class HistoricalReport(BaseModel):
    """Cross-upload view — 'how has our supply chain changed over the year?'"""

    points: list[HistoricalPoint]
    direction: str
    summary: str
