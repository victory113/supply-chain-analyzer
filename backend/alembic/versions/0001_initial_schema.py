"""Initial schema: users, uploads, shipments, analyses, risks

Revision ID: 0001
Revises:
Create Date: 2026-07-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB()
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255)),
        sa.Column("organization", sa.String(255)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "uploads",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "user_id",
            UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "rejected_row_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text()),
        sa.Column("label", sa.String(255)),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_uploads_id", "uploads", ["id"])
    op.create_index("ix_uploads_user_id", "uploads", ["user_id"])
    op.create_index("ix_uploads_status", "uploads", ["status"])

    op.create_table(
        "shipments",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "upload_id",
            UUID,
            sa.ForeignKey("uploads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("shipment_ref", sa.String(128)),
        sa.Column("vendor", sa.String(255)),
        sa.Column("product", sa.String(255)),
        sa.Column("origin_country", sa.String(128)),
        sa.Column("destination", sa.String(255)),
        sa.Column("quantity", sa.Integer()),
        sa.Column("unit_cost", sa.Numeric(14, 4)),
        sa.Column("lead_time_days", sa.Integer()),
        sa.Column("delay_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("shipped_on", sa.Date()),
        sa.Column("last_updated", sa.Date()),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_shipments_id", "shipments", ["id"])
    op.create_index("ix_shipments_upload_id", "shipments", ["upload_id"])
    op.create_index("ix_shipments_shipment_ref", "shipments", ["shipment_ref"])
    op.create_index("ix_shipments_vendor", "shipments", ["vendor"])
    op.create_index("ix_shipments_origin_country", "shipments", ["origin_country"])
    op.create_index("ix_shipments_status", "shipments", ["status"])
    op.create_index("ix_shipments_upload_vendor", "shipments", ["upload_id", "vendor"])
    op.create_index(
        "ix_shipments_upload_country", "shipments", ["upload_id", "origin_country"]
    )

    op.create_table(
        "analyses",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "upload_id",
            UUID,
            sa.ForeignKey("uploads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("summary", sa.Text()),
        sa.Column("overall_risk", sa.String(16)),
        sa.Column("risk_score", sa.Float()),
        sa.Column("healthy_signals", JSONB),
        sa.Column("metrics_snapshot", JSONB),
        sa.Column("model_name", sa.String(64)),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("task_id", sa.String(128)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_analyses_id", "analyses", ["id"])
    op.create_index("ix_analyses_upload_id", "analyses", ["upload_id"])
    op.create_index("ix_analyses_status", "analyses", ["status"])
    op.create_index("ix_analyses_task_id", "analyses", ["task_id"])

    op.create_table(
        "risks",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "analysis_id",
            UUID,
            sa.ForeignKey("analyses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("risk_level", sa.String(16), nullable=False, server_default="MEDIUM"),
        sa.Column("explanation", sa.Text()),
        sa.Column("recommendation", sa.Text()),
        sa.Column("affected_items", JSONB),
        sa.Column("evidence_metric", sa.String(128)),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_risks_id", "risks", ["id"])
    op.create_index("ix_risks_analysis_id", "risks", ["analysis_id"])
    op.create_index("ix_risks_risk_level", "risks", ["risk_level"])


def downgrade() -> None:
    op.drop_table("risks")
    op.drop_table("analyses")
    op.drop_table("shipments")
    op.drop_table("uploads")
    op.drop_table("users")
