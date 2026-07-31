"""Model package.

Every model must be imported here so Alembic's autogenerate and
``Base.metadata.create_all`` see the full table set.
"""

from app.db.base import Base
from app.models.analysis import Analysis, Risk
from app.models.enums import (
    AnalysisStatus,
    RiskLevel,
    ShipmentStatus,
    UploadStatus,
)
from app.models.shipment import Shipment
from app.models.upload import Upload
from app.models.user import User

__all__ = [
    "Analysis",
    "AnalysisStatus",
    "Base",
    "Risk",
    "RiskLevel",
    "Shipment",
    "ShipmentStatus",
    "Upload",
    "UploadStatus",
    "User",
]
