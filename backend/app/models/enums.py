"""Enumerations shared by models, schemas, and the analytics engine.

Stored as strings rather than native PG enums so adding a value doesn't require
a migration that rewrites the type.
"""

from __future__ import annotations

from enum import StrEnum


class UploadStatus(StrEnum):
    PENDING = "pending"
    PARSING = "parsing"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"


class ShipmentStatus(StrEnum):
    ON_TIME = "on_time"
    DELAYED = "delayed"
    CRITICAL = "critical"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, raw: str | None) -> ShipmentStatus:
        """Map free-text CSV status values onto the enum.

        Real exports are inconsistent ("On Time", "ON-TIME", "in transit"), so
        normalise aggressively and fall back to UNKNOWN rather than rejecting
        the row.
        """
        if not raw:
            return cls.UNKNOWN
        normalized = raw.strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "ontime": cls.ON_TIME,
            "on_time": cls.ON_TIME,
            "in_transit": cls.ON_TIME,
            "intransit": cls.ON_TIME,
            "shipping_on_time": cls.ON_TIME,
            "advance_shipping": cls.ON_TIME,
            "early": cls.ON_TIME,
            "processing": cls.ON_TIME,
            "pending": cls.ON_TIME,
            "late": cls.DELAYED,
            "delay": cls.DELAYED,
            "delayed": cls.DELAYED,
            "at_risk": cls.DELAYED,
            "late_delivery": cls.DELAYED,
            "backordered": cls.DELAYED,
            "critical": cls.CRITICAL,
            "severe": cls.CRITICAL,
            "blocked": cls.CRITICAL,
            "on_hold": cls.CRITICAL,
            "exception": cls.CRITICAL,
            "delivered": cls.DELIVERED,
            "complete": cls.DELIVERED,
            "completed": cls.DELIVERED,
            "closed": cls.DELIVERED,
            "fulfilled": cls.DELIVERED,
            "received": cls.DELIVERED,
            "cancelled": cls.CANCELLED,
            "canceled": cls.CANCELLED,
            "shipping_canceled": cls.CANCELLED,
            "shipping_cancelled": cls.CANCELLED,
            "returned": cls.CANCELLED,
            "void": cls.CANCELLED,
        }
        return aliases.get(normalized, cls.UNKNOWN)


class TransportMode(StrEnum):
    """How the goods moved. Drives mode-vs-mode performance and CO2 factors."""

    AIR = "air"
    OCEAN = "ocean"
    ROAD = "road"
    RAIL = "rail"
    PARCEL = "parcel"
    MULTIMODAL = "multimodal"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, raw: str | None) -> TransportMode:
        if not raw:
            return cls.UNKNOWN
        normalized = raw.strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "air": cls.AIR,
            "air_freight": cls.AIR,
            "airfreight": cls.AIR,
            "flight": cls.AIR,
            "plane": cls.AIR,
            "ocean": cls.OCEAN,
            "sea": cls.OCEAN,
            "sea_freight": cls.OCEAN,
            "vessel": cls.OCEAN,
            "ship": cls.OCEAN,
            "maritime": cls.OCEAN,
            "fcl": cls.OCEAN,
            "lcl": cls.OCEAN,
            "road": cls.ROAD,
            "truck": cls.ROAD,
            "trucking": cls.ROAD,
            "ltl": cls.ROAD,
            "ftl": cls.ROAD,
            "ground": cls.ROAD,
            "rail": cls.RAIL,
            "train": cls.RAIL,
            "intermodal": cls.MULTIMODAL,
            "multimodal": cls.MULTIMODAL,
            "parcel": cls.PARCEL,
            "courier": cls.PARCEL,
            "express": cls.PARCEL,
            "small_parcel": cls.PARCEL,
        }
        return aliases.get(normalized, cls.UNKNOWN)


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

    @property
    def rank(self) -> int:
        return {"LOW": 0, "MEDIUM": 1, "HIGH": 2}[self.value]

    @classmethod
    def from_score(cls, score: float) -> RiskLevel:
        """Bucket a 0-100 risk score. Thresholds live here so the API, the
        dashboard, and the LLM prompt all agree on what 'HIGH' means."""
        if score >= 66:
            return cls.HIGH
        if score >= 33:
            return cls.MEDIUM
        return cls.LOW


class AnalysisStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
