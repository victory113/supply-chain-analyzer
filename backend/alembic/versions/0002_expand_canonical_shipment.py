"""Expand the canonical shipment model

Widens `shipments` from the original 14 fields to the full canonical record so
exports from ERP, WMS, TMS and carrier systems can be normalised into one
shape. Every added column is nullable: a file that carries none of them is
still a valid upload, and a field the source never provided must stay NULL
rather than default to a zero that reads as a measurement.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (name, type) — all nullable, all added to `shipments`.
NEW_COLUMNS: list[tuple[str, sa.types.TypeEngine]] = [
    # Identifiers
    ("order_ref", sa.String(128)),
    ("tracking_number", sa.String(128)),
    ("customer_ref", sa.String(128)),
    # Parties
    ("carrier", sa.String(255)),
    ("customer", sa.String(255)),
    ("service_level", sa.String(64)),
    # Product
    ("sku", sa.String(128)),
    ("category", sa.String(128)),
    ("brand", sa.String(128)),
    ("quantity_delivered", sa.Integer()),
    ("currency", sa.String(8)),
    ("weight_kg", sa.Numeric(14, 3)),
    ("hazardous", sa.Boolean()),
    ("temperature_controlled", sa.Boolean()),
    # Geography
    ("origin_city", sa.String(128)),
    ("destination_country", sa.String(128)),
    ("destination_city", sa.String(128)),
    ("warehouse", sa.String(128)),
    # Transport
    ("transport_mode", sa.String(32)),
    ("container_ref", sa.String(64)),
    ("vehicle_ref", sa.String(64)),
    ("route_ref", sa.String(64)),
    ("package_count", sa.Integer()),
    ("distance_km", sa.Numeric(12, 2)),
    # Timing
    ("transit_days", sa.Integer()),
    ("priority", sa.String(32)),
    ("scheduled_delivery", sa.Date()),
    ("actual_delivery", sa.Date()),
    # Money
    ("freight_cost", sa.Numeric(14, 4)),
    ("insurance_cost", sa.Numeric(14, 4)),
    ("customs_duty", sa.Numeric(14, 4)),
    ("total_cost", sa.Numeric(14, 4)),
    # Quality
    ("damaged", sa.Boolean()),
    ("returned", sa.Boolean()),
    # Customs
    ("incoterms", sa.String(16)),
    ("hs_code", sa.String(32)),
    # Sustainability
    ("co2_kg", sa.Numeric(14, 3)),
]


def upgrade() -> None:
    # Plain ALTERs: migrations only ever run against Postgres. SQLite dev mode
    # creates its schema from the models at startup (app/db/init_db.py) and
    # refuses to run Alembic at all, so there is no engine here that needs the
    # table-rebuild dance.
    for name, column_type in NEW_COLUMNS:
        op.add_column("shipments", sa.Column(name, column_type, nullable=True))

    op.create_index("ix_shipments_upload_carrier", "shipments", ["upload_id", "carrier"])
    op.create_index("ix_shipments_transport_mode", "shipments", ["transport_mode"])


def downgrade() -> None:
    op.drop_index("ix_shipments_transport_mode", table_name="shipments")
    op.drop_index("ix_shipments_upload_carrier", table_name="shipments")

    for name, _ in reversed(NEW_COLUMNS):
        op.drop_column("shipments", name)
