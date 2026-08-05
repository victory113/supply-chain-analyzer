"""Deterministic supply-chain analytics.

Pure functions over ``ShipmentFact`` records — no I/O, no network, no LLM.
This is the layer that owns every number the product reports.
"""

from app.services.analytics.countries import score_countries
from app.services.analytics.dimensions import (
    score_carriers,
    score_categories,
    score_dimension,
    score_lanes,
    score_service_levels,
    score_transport_modes,
)
from app.services.analytics.engine import (
    build_historical_report,
    build_report,
    describe_coverage,
    find_healthy_signals,
)
from app.services.analytics.facts import ShipmentFact
from app.services.analytics.kpis import compute_kpis
from app.services.analytics.operations import (
    build_cost_summary,
    build_emissions_summary,
    build_quality_summary,
)
from app.services.analytics.risk import compute_risk, describe_drivers
from app.services.analytics.trends import build_trend
from app.services.analytics.vendors import score_vendors

__all__ = [
    "ShipmentFact",
    "build_cost_summary",
    "build_emissions_summary",
    "build_historical_report",
    "build_quality_summary",
    "build_report",
    "build_trend",
    "compute_kpis",
    "compute_risk",
    "describe_coverage",
    "describe_drivers",
    "find_healthy_signals",
    "score_carriers",
    "score_categories",
    "score_countries",
    "score_dimension",
    "score_lanes",
    "score_service_levels",
    "score_transport_modes",
    "score_vendors",
]
