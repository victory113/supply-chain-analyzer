"""Deterministic supply-chain analytics.

Pure functions over ``ShipmentFact`` records — no I/O, no network, no LLM.
This is the layer that owns every number the product reports.
"""

from app.services.analytics.countries import score_countries
from app.services.analytics.engine import (
    build_historical_report,
    build_report,
    find_healthy_signals,
)
from app.services.analytics.facts import ShipmentFact
from app.services.analytics.kpis import compute_kpis
from app.services.analytics.risk import compute_risk, describe_drivers
from app.services.analytics.trends import build_trend
from app.services.analytics.vendors import score_vendors

__all__ = [
    "ShipmentFact",
    "build_historical_report",
    "build_report",
    "build_trend",
    "compute_kpis",
    "compute_risk",
    "describe_drivers",
    "find_healthy_signals",
    "score_countries",
    "score_vendors",
]
