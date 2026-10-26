"""C11.5 — Economic Optimization Engine tables.

Revision ID: c11_05_econ
Revises: c11_04_agent_strategy
Create Date: 2025-01-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "c11_05_econ"
down_revision = "c11_04_agent_strategy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- optimization_plans --
    op.create_table(
        "optimization_plans",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("optimization_id", sa.String(64), unique=True, nullable=False),
        sa.Column("plan_version", sa.String(16), nullable=False, server_default="1"),
        sa.Column("task_profile_id", sa.String(64), nullable=False, index=True),
        sa.Column("workspace_id", sa.String(64), nullable=False, index=True),
        sa.Column("selected_candidate_json", JSONB, nullable=False),
        sa.Column("alternatives_json", JSONB, nullable=True),
        sa.Column("estimated_quality", sa.Float, nullable=True),
        sa.Column("estimated_reliability", sa.Float, nullable=True),
        sa.Column("estimated_cost", sa.Float, nullable=True),
        sa.Column("estimated_latency_ms", sa.Integer, nullable=True),
        sa.Column("authorized_budget", sa.Float, nullable=True),
        sa.Column("budget_limits_json", JSONB, nullable=True),
        sa.Column("optimization_policy", sa.String(32), nullable=False, server_default="balanced"),
        sa.Column("constraints_json", JSONB, nullable=True),
        sa.Column("decision_reasons_json", JSONB, nullable=True),
        sa.Column("limitations_json", JSONB, nullable=True),
        sa.Column("approval_required", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="dsrt",
    )

    # -- prediction_records --
    op.create_table(
        "prediction_records",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("optimization_id", sa.String(64), nullable=False, index=True),
        sa.Column("candidate_id", sa.String(64), nullable=False),
        sa.Column("predicted_quality", sa.Float, nullable=True),
        sa.Column("predicted_reliability", sa.Float, nullable=True),
        sa.Column("predicted_cost", sa.Float, nullable=True),
        sa.Column("predicted_latency_ms", sa.Integer, nullable=True),
        sa.Column("evidence_confidence", sa.Float, nullable=True),
        sa.Column("actual_quality", sa.Float, nullable=True),
        sa.Column("actual_reliability", sa.Float, nullable=True),
        sa.Column("actual_cost", sa.Float, nullable=True),
        sa.Column("actual_latency_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="dsrt",
    )


def downgrade() -> None:
    op.drop_table("prediction_records", schema="dsrt")
    op.drop_table("optimization_plans", schema="dsrt")