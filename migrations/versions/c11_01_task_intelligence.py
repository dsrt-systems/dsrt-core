"""c11_01_task_intelligence

Revision ID: c11_01_task_intelligence
Revises: c10_10_comparison
Create Date: 2026-03-31 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'c11_01_task_intelligence'
down_revision = 'c10_initial'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'task_profiles',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('task_id', sa.String(length=128), nullable=False),
        sa.Column('organization_id', sa.String(length=128), nullable=False),
        sa.Column('primary_domain', sa.String(length=64), nullable=False),
        sa.Column('primary_intent', sa.String(length=64), nullable=False),
        sa.Column('complexity_score', sa.Float(), nullable=False),
        sa.Column('complexity_level', sa.String(length=32), nullable=False),
        sa.Column('risk_level', sa.String(length=32), nullable=False),
        sa.Column('risk_score', sa.Float(), nullable=False),
        sa.Column('raw_profile_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_task_profiles_org_domain', 'task_profiles', ['organization_id', 'primary_domain'], unique=False)
    op.create_index('ix_task_profiles_org_task', 'task_profiles', ['organization_id', 'task_id'], unique=False)
    op.create_index('ix_task_profiles_task_id', 'task_profiles', ['task_id'], unique=False)
    op.create_index('ix_task_profiles_organization_id', 'task_profiles', ['organization_id'], unique=False)

    op.create_table(
        'optimization_requests',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('task_profile_id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=128), nullable=False),
        sa.Column('optimization_goal', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('request_metadata_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['task_profile_id'], ['task_profiles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_opt_requests_org_status', 'optimization_requests', ['organization_id', 'status'], unique=False)
    op.create_index('ix_optimization_requests_organization_id', 'optimization_requests', ['organization_id'], unique=False)


def downgrade():
    op.drop_table('optimization_requests')
    op.drop_table('task_profiles')