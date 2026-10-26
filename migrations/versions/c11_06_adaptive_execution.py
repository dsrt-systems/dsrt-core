"""C11.6 — Adaptive Execution Controller tables.

Revision ID: c11_06_adapt
Revises: c11_05_econ
Create Date: 2025-01-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "c11_06_adapt"
down_revision = "c11_05_econ"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "adaptation_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("execution_id", sa.String(64), nullable=False, index=True),
        sa.Column("decision_id", sa.String(64), nullable=False, index=True),
        sa.Column("trigger_type", sa.String(64), nullable=False),
        sa.Column("action_type", sa.String(64), nullable=False),
        sa.Column("target_model", sa.String(128), nullable=True),
        sa.Column("target_tool", sa.String(128), nullable=True),
        sa.Column("estimated_cost", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("requires_approval", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(32), nullable=False, server_default="proposed"),
        sa.Column("reason", sa.String(512), nullable=False),
        sa.Column("details_json", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="dsrt",
    )


def downgrade() -> None:
    op.drop_table("adaptation_events", schema="dsrt")