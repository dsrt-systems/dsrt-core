"""c11_08_strategy_learning

Revision ID: c11_08_learn
Revises: c11_07_verif
Create Date: 2026-03-31 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c11_08_learn'
down_revision: Union[str, None] = 'c11_07_verif'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    schema = 'dsrt' if is_postgres else None

    op.create_table(
        'strategy_arm_states',
        sa.Column('arm_id', sa.String(length=64), nullable=False),
        sa.Column('strategy_name', sa.String(length=64), nullable=False),
        sa.Column('pull_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_reward', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('mean_reward', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('alpha', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('beta', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('ucb_score', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('last_updated', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('arm_id'),
        schema=schema
    )

    op.create_table(
        'learning_observations',
        sa.Column('observation_id', sa.String(length=64), nullable=False),
        sa.Column('strategy_id', sa.String(length=64), nullable=False),
        sa.Column('task_id', sa.String(length=64), nullable=False),
        sa.Column('quality_score', sa.Float(), nullable=False),
        sa.Column('cost_usd', sa.Float(), nullable=False),
        sa.Column('latency_ms', sa.Float(), nullable=False),
        sa.Column('scalar_reward', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('observation_id'),
        schema=schema
    )

    if is_postgres:
        op.create_index('ix_dsrt_learning_observations_strategy_id', 'learning_observations', ['strategy_id'], schema='dsrt')
        op.create_index('ix_dsrt_learning_observations_task_id', 'learning_observations', ['task_id'], schema='dsrt')
    else:
        op.create_index('ix_learning_observations_strategy_id', 'learning_observations', ['strategy_id'])
        op.create_index('ix_learning_observations_task_id', 'learning_observations', ['task_id'])


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    schema = 'dsrt' if is_postgres else None

    op.drop_table('learning_observations', schema=schema)
    op.drop_table('strategy_arm_states', schema=schema)