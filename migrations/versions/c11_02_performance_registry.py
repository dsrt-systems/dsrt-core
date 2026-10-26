"""c11_02_performance_registry

Revision ID: c11_02_performance_registry
Revises: c11_01_task_intelligence
Create Date: 2026-03-31 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'c11_02_performance_registry'
down_revision = 'c11_01_task_intelligence'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'performance_evidence',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('model_id', sa.String(length=128), nullable=False),
        sa.Column('organization_id', sa.String(length=128), nullable=False),
        sa.Column('domain', sa.String(length=64), nullable=False),
        sa.Column('intent', sa.String(length=64), nullable=False),
        sa.Column('complexity_level', sa.String(length=32), nullable=False),
        sa.Column('quality_score', sa.Float(), nullable=False),
        sa.Column('reliability_score', sa.Float(), nullable=False),
        sa.Column('latency_ms', sa.Float(), nullable=False),
        sa.Column('total_tokens', sa.Integer(), nullable=False),
        sa.Column('cost_usd', sa.Float(), nullable=False),
        sa.Column('error_type', sa.String(length=64), nullable=True),
        sa.Column('raw_evidence_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_perf_evidence_model_ctx', 'performance_evidence', ['model_id', 'domain', 'intent', 'complexity_level'], unique=False)
    op.create_index('ix_perf_evidence_org_model', 'performance_evidence', ['organization_id', 'model_id'], unique=False)

    op.create_table(
        'model_performance_profiles',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('model_id', sa.String(length=128), nullable=False),
        sa.Column('organization_id', sa.String(length=128), nullable=False),
        sa.Column('domain', sa.String(length=64), nullable=False),
        sa.Column('intent', sa.String(length=64), nullable=False),
        sa.Column('complexity_level', sa.String(length=32), nullable=False),
        sa.Column('sample_count', sa.Integer(), nullable=False),
        sa.Column('quality_mean', sa.Float(), nullable=False),
        sa.Column('reliability_rate', sa.Float(), nullable=False),
        sa.Column('latency_p50', sa.Float(), nullable=False),
        sa.Column('latency_p90', sa.Float(), nullable=False),
        sa.Column('cost_mean', sa.Float(), nullable=False),
        sa.Column('raw_profile_json', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_model_perf_profiles_model_ctx', 'model_performance_profiles', ['model_id', 'domain', 'intent', 'complexity_level'], unique=False)
    op.create_index('ix_model_perf_profiles_org_model', 'model_performance_profiles', ['organization_id', 'model_id'], unique=False)

    op.create_table(
        'configuration_profiles',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=128), nullable=False),
        sa.Column('model_id', sa.String(length=128), nullable=False),
        sa.Column('system_prompt_hash', sa.String(length=64), nullable=False),
        sa.Column('raw_config_json', sa.Text(), nullable=False),
        sa.Column('performance_summary_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_config_profiles_org_model', 'configuration_profiles', ['organization_id', 'model_id'], unique=False)


def downgrade():
    op.drop_table('configuration_profiles')
    op.drop_table('model_performance_profiles')
    op.drop_table('performance_evidence')