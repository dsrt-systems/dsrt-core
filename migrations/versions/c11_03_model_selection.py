"""C11-03: Model selection and configuration profiles.

Revision ID: c11_03_model_selection
Revises: c11_02_performance_registry
Create Date: 2025-01-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c11_03_model_selection"
down_revision = "c11_02_performance_registry"
branch_labels = None
depends_on = None

SCHEMA = "dsrt"


def upgrade() -> None:
    # Model selection policies
    op.create_table(
        "model_selection_policies",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("organization_id", sa.String(64), sa.ForeignKey(f"{SCHEMA}.organizations.id"), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=True),
        sa.Column("task_family", sa.String(128), nullable=True),
        sa.Column("selection_mode", sa.String(32), nullable=False, server_default="automatic"),
        sa.Column("preferred_model_id", sa.String(64), nullable=True),
        sa.Column("preferred_provider", sa.String(128), nullable=True),
        sa.Column("fallback_chain", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("max_cost_per_call_usd", sa.Float, nullable=True),
        sa.Column("min_capability_score", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("ix_c11_msp_org", "model_selection_policies", ["organization_id"], schema=SCHEMA)
    op.create_index("ix_c11_msp_mode", "model_selection_policies", ["selection_mode"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("model_selection_policies", schema=SCHEMA)