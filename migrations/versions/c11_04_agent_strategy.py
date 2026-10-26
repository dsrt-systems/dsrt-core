"""c11_04_agent_strategy

Revision ID: c11_04_agent_strategy
Revises: c11_02_performance_registry
Create Date: 2026-03-31 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'c11_04_agent_strategy'
down_revision = 'c11_03_model_selection'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'strategy_definitions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=128), nullable=False),
        sa.Column('strategy_name', sa.String(length=128), nullable=False),
        sa.Column('strategy_type', sa.String(length=64), nullable=False),
        sa.Column('topology_type', sa.String(length=64), nullable=False),
        sa.Column('raw_config_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_strat_defs_org_name', 'strategy_definitions', ['organization_id', 'strategy_name'], unique=False)
    op.create_index('ix_strategy_definitions_organization_id', 'strategy_definitions', ['organization_id'], unique=False)

    op.create_table(
        'strategy_versions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('strategy_id', sa.String(length=36), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('hyperparameters_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['strategy_id'], ['strategy_definitions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_strat_versions_strat_ver', 'strategy_versions', ['strategy_id', 'version_number'], unique=False)


def downgrade():
    op.drop_table('strategy_versions')
    op.drop_table('strategy_definitions')