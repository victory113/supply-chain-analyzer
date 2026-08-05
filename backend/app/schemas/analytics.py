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


class DimensionScore(BaseModel):
    """Performance for one value of a dimension — a carrier, a mode, a lane.

    One shape serves all of them so the frontend can render any breakdown with
    a single component instead of one per dimension.
    """

    label: str
    shipment_count: int
    share_pct: float
    late_count: int
    late_pct: float
    avg_delay_days: float
    # None when the file carried no transit/freight data for this group, which
    # is not the same as zero.
    avg_transit_days: float | None = None
    total_value: float
    avg_freight_cost: float | None = None


class CostSummary(BaseModel):
    """Freight economics. Present only when the upload carried cost columns."""

    coverage_pct: float = Field(description="Share of rows that carried a freight cost")
    total_freight_cost: float
    avg_freight_cost: float
    freight_per_unit: float | None = None
    freight_per_kg: float | None = None
    freight_pct_of_goods: float | None = Field(
        default=None, description="Freight spend as a share of goods value"
    )
    total_landed_cost: float | None = None
    freight_spent_on_late_shipments: float


class QualitySummary(BaseModel):
    """Damage, returns, fill rate. Each metric independently optional."""

    damage_rate_pct: float | None = None
    damaged_count: int | None = None
    return_rate_pct: float | None = None
    returned_count: int | None = None
    avg_fill_rate_pct: float | None = None
    perfect_order_rate_pct: float = Field(
        description="On time, undamaged, not returned, fully filled"
    )
    coverage_pct: float


class EmissionsSummary(BaseModel):
    """CO2e, read from the file or estimated from mode/distance/weight."""

    coverage_pct: float
    total_co2_kg: float
    avg_co2_per_shipment_kg: float
    co2_by_mode_kg: dict[str, float]


class AnalyticsReport(BaseModel):
    """The full deterministic report.

    Sections below `healthy_signals` are all optional and are omitted entirely
    when the upload lacked the columns to compute them. An absent section means
    "this file couldn't answer that question" — never "the answer is zero".
    """

    upload_id: str
    kpis: KpiSummary
    vendors: list[VendorScore]
    countries: list[CountryRisk]
    trend: TrendAnalysis
    risk: RiskBreakdown
    healthy_signals: list[str]

    # Optional dimensions
    carriers: list[DimensionScore] = []
    transport_modes: list[DimensionScore] = []
    service_levels: list[DimensionScore] = []
    categories: list[DimensionScore] = []
    lanes: list[DimensionScore] = []

    # Optional summaries
    cost: CostSummary | None = None
    quality: QualitySummary | None = None
    emissions: EmissionsSummary | None = None

    # Which canonical fields this upload actually populated, so the UI can
    # explain what's missing instead of silently showing less.
    available_dimensions: list[str] = []


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
