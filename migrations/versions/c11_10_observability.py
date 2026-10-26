"""c11_10_obs

Revision ID: c11_10_obs
Revises: c11_09_gov
Create Date: 2025-02-15 12:00:00.000000

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c11_10_obs"
down_revision: Union[str, None] = "c11_09_gov"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reconciliation_reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=255), nullable=False),
        sa.Column("plan_id", sa.String(length=255), nullable=False),
        sa.Column("organization_id", sa.String(length=255), nullable=False),
        sa.Column("predicted_cost_usd", sa.Float(), nullable=False),
        sa.Column("actual_cost_usd", sa.Float(), nullable=False),
        sa.Column("cost_error_pct", sa.Float(), nullable=False),
        sa.Column("predicted_latency_ms", sa.Float(), nullable=False),
        sa.Column("actual_latency_ms", sa.Float(), nullable=False),
        sa.Column("latency_error_pct", sa.Float(), nullable=False),
        sa.Column("predicted_quality_score", sa.Float(), nullable=False),
        sa.Column("actual_quality_score", sa.Float(), nullable=False),
        sa.Column("quality_error_pct", sa.Float(), nullable=False),
        sa.Column(
            "reconciled_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="dsrt",
    )
    op.create_index(
        "idx_recon_tenant",
        "reconciliation_reports",
        ["organization_id"],
        unique=False,
        schema="dsrt",
    )
    op.create_index(
        "idx_recon_request",
        "reconciliation_reports",
        ["request_id"],
        unique=False,
        schema="dsrt",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_recon_request",
        table_name="reconciliation_reports",
        schema="dsrt",
    )
    op.drop_index(
        "idx_recon_tenant", table_name="reconciliation_reports", schema="dsrt"
    )
    op.drop_table("reconciliation_reports", schema="dsrt")