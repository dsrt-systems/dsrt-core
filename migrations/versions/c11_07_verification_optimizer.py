"""c11_07_verification_optimizer

Revision ID: c11_07_verif
Revises: c11_06_adapt
Create Date: 2026-03-31 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c11_07_verif'
down_revision: Union[str, None] = 'c11_06_adapt'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Check dialect for JSON type selection
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    json_type = postgresql.JSONB(astext_type=sa.Text()) if is_postgres else sa.JSON()

    op.create_table(
        'verification_pipelines',
        sa.Column('pipeline_id', sa.String(length=64), nullable=False),
        sa.Column('task_id', sa.String(length=64), nullable=False),
        sa.Column('strategy_type', sa.String(length=32), nullable=False),
        sa.Column('steps_json', json_type, nullable=False),
        sa.Column('total_cost', sa.Float(), nullable=False),
        sa.Column('total_latency_sec', sa.Float(), nullable=False),
        sa.Column('expected_confidence', sa.Float(), nullable=False),
        sa.Column('early_exit_on_failure', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('pipeline_id'),
        schema='dsrt' if is_postgres else None
    )

    if is_postgres:
        op.create_index(
            'ix_dsrt_verification_pipelines_task_id',
            'verification_pipelines',
            ['task_id'],
            unique=False,
            schema='dsrt'
        )
    else:
        op.create_index(
            'ix_verification_pipelines_task_id',
            'verification_pipelines',
            ['task_id'],
            unique=False
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    schema = 'dsrt' if is_postgres else None

    op.drop_table('verification_pipelines', schema=schema)