"""c11_09_governance

Revision ID: c11_09_gov
Revises: c11_08_learn
Create Date: 2026-04-01 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c11_09_gov'
down_revision: Union[str, None] = 'c11_08_learn'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    schema = 'dsrt' if is_postgres else None
    json_type = postgresql.JSONB(astext_type=sa.Text()) if is_postgres else sa.JSON()

    # optimization_policies
    op.create_table(
        'optimization_policies',
        sa.Column('policy_id', sa.String(length=64), nullable=False),
        sa.Column('organization_id', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=True),
        sa.Column('policy_name', sa.String(length=128), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('optimization_mode', sa.String(length=32), nullable=False, server_default='balanced'),
        sa.Column('preferred_models', json_type, nullable=False),
        sa.Column('allowed_models', json_type, nullable=False),
        sa.Column('forbidden_models', json_type, nullable=False),
        sa.Column('model_selection_lock', sa.String(length=32), nullable=False, server_default='automatic'),
        sa.Column('preferred_agents', json_type, nullable=False),
        sa.Column('allowed_agents', json_type, nullable=False),
        sa.Column('max_cost_usd_per_task', sa.Float(), nullable=True),
        sa.Column('max_latency_ms_per_task', sa.Float(), nullable=True),
        sa.Column('min_quality_score', sa.Float(), nullable=False, server_default='0.70'),
        sa.Column('min_reliability_score', sa.Float(), nullable=False, server_default='0.80'),
        sa.Column('allow_model_escalation', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('allow_strategy_adaptation', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('require_mandatory_security_checks', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('approval_required_for_budget_override', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('approval_required_for_model_change', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('approval_required_for_sensitive_tools', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('enforcement_level', sa.String(length=32), nullable=False, server_default='strict'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.PrimaryKeyConstraint('policy_id'),
        schema=schema,
    )

    # optimization_decisions
    op.create_table(
        'optimization_decisions',
        sa.Column('decision_id', sa.String(length=64), nullable=False),
        sa.Column('optimization_id', sa.String(length=64), nullable=False),
        sa.Column('task_id', sa.String(length=64), nullable=False),
        sa.Column('organization_id', sa.String(length=64), nullable=False),
        sa.Column('decision_type', sa.String(length=32), nullable=False),
        sa.Column('decision_subject', sa.String(length=128), nullable=False),
        sa.Column('chosen_option', sa.String(length=128), nullable=False),
        sa.Column('rejected_options', json_type, nullable=False),
        sa.Column('decision_reasons', json_type, nullable=False),
        sa.Column('evidence_references', json_type, nullable=False),
        sa.Column('policy_id', sa.String(length=64), nullable=True),
        sa.Column('confidence_score', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('decision_id'),
        schema=schema,
    )

    # optimization_snapshots
    op.create_table(
        'optimization_snapshots',
        sa.Column('snapshot_id', sa.String(length=64), nullable=False),
        sa.Column('optimization_id', sa.String(length=64), nullable=False),
        sa.Column('task_id', sa.String(length=64), nullable=False),
        sa.Column('organization_id', sa.String(length=64), nullable=False),
        sa.Column('plan_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('task_profile_json', json_type, nullable=False),
        sa.Column('selected_model', sa.String(length=128), nullable=False),
        sa.Column('selected_agent', sa.String(length=128), nullable=True),
        sa.Column('selected_strategies', json_type, nullable=False),
        sa.Column('verification_plan_json', json_type, nullable=False),
        sa.Column('policy_snapshot_json', json_type, nullable=False),
        sa.Column('evidence_snapshot_json', json_type, nullable=False),
        sa.Column('estimated_cost', sa.Float(), nullable=False),
        sa.Column('estimated_latency_ms', sa.Float(), nullable=False),
        sa.Column('estimated_quality', sa.Float(), nullable=False),
        sa.Column('approved_by', sa.String(length=64), nullable=True),
        sa.Column('approval_timestamp', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('snapshot_id'),
        schema=schema,
    )

    # learning_candidates
    op.create_table(
        'learning_candidates',
        sa.Column('candidate_id', sa.String(length=64), nullable=False),
        sa.Column('organization_id', sa.String(length=64), nullable=False, server_default='global'),
        sa.Column('candidate_type', sa.String(length=64), nullable=False),
        sa.Column('description', sa.String(length=512), nullable=False),
        sa.Column('proposed_change_json', json_type, nullable=False),
        sa.Column('baseline_metrics_json', json_type, nullable=False),
        sa.Column('expected_improvement_json', json_type, nullable=False),
        sa.Column('evidence_references', json_type, nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='proposed'),
        sa.Column('validation_results_json', json_type, nullable=False),
        sa.Column('experiment_id', sa.String(length=64), nullable=True),
        sa.Column('promoted_at', sa.DateTime(), nullable=True),
        sa.Column('rolled_back_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('candidate_id'),
        schema=schema,
    )

    # strategy_experiments
    op.create_table(
        'strategy_experiments',
        sa.Column('experiment_id', sa.String(length=64), nullable=False),
        sa.Column('organization_id', sa.String(length=64), nullable=False, server_default='global'),
        sa.Column('experiment_name', sa.String(length=128), nullable=False),
        sa.Column('hypothesis', sa.String(length=512), nullable=False),
        sa.Column('control_config_json', json_type, nullable=False),
        sa.Column('treatment_config_json', json_type, nullable=False),
        sa.Column('sample_size_target', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('sample_size_actual', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('control_metrics_json', json_type, nullable=False),
        sa.Column('treatment_metrics_json', json_type, nullable=False),
        sa.Column('statistical_significance', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='planned'),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('experiment_id'),
        schema=schema,
    )

    # profile_versions
    op.create_table(
        'profile_versions',
        sa.Column('version_id', sa.String(length=64), nullable=False),
        sa.Column('profile_type', sa.String(length=32), nullable=False),
        sa.Column('profile_subject', sa.String(length=128), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('profile_snapshot_json', json_type, nullable=False),
        sa.Column('sample_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('valid_from', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('valid_until', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('version_id'),
        schema=schema,
    )

    # agent_performance_profiles
    op.create_table(
        'agent_performance_profiles',
        sa.Column('profile_id', sa.String(length=64), nullable=False),
        sa.Column('organization_id', sa.String(length=64), nullable=False, server_default='global'),
        sa.Column('agent_id', sa.String(length=64), nullable=False),
        sa.Column('agent_version', sa.String(length=32), nullable=False, server_default='1.0.0'),
        sa.Column('model_id', sa.String(length=64), nullable=False),
        sa.Column('task_domain', sa.String(length=32), nullable=False),
        sa.Column('total_runs', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('success_rate', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('avg_quality', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('avg_latency_ms', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('avg_cost_usd', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('confidence_score', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('profile_id'),
        schema=schema,
    )

    # strategy_performance_profiles
    op.create_table(
        'strategy_performance_profiles',
        sa.Column('profile_id', sa.String(length=64), nullable=False),
        sa.Column('organization_id', sa.String(length=64), nullable=False, server_default='global'),
        sa.Column('strategy_id', sa.String(length=64), nullable=False),
        sa.Column('strategy_version', sa.String(length=32), nullable=False, server_default='1.0.0'),
        sa.Column('task_domain', sa.String(length=32), nullable=False),
        sa.Column('baseline_quality', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('strategy_quality', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('quality_improvement', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('incremental_cost_usd', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('incremental_latency_ms', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('value_ratio', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('sample_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('confidence_score', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('profile_id'),
        schema=schema,
    )

    # fallback_states
    op.create_table(
        'fallback_states',
        sa.Column('state_id', sa.String(length=64), nullable=False),
        sa.Column('mode', sa.String(length=32), nullable=False, server_default='healthy'),
        sa.Column('failure_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_failure_at', sa.DateTime(), nullable=True),
        sa.Column('last_success_at', sa.DateTime(), nullable=True),
        sa.Column('circuit_opened_at', sa.DateTime(), nullable=True),
        sa.Column('reason', sa.String(length=512), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('state_id'),
        schema=schema,
    )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    schema = 'dsrt' if is_postgres else None

    op.drop_table('fallback_states', schema=schema)
    op.drop_table('strategy_performance_profiles', schema=schema)
    op.drop_table('agent_performance_profiles', schema=schema)
    op.drop_table('profile_versions', schema=schema)
    op.drop_table('strategy_experiments', schema=schema)
    op.drop_table('learning_candidates', schema=schema)
    op.drop_table('optimization_snapshots', schema=schema)
    op.drop_table('optimization_decisions', schema=schema)
    op.drop_table('optimization_policies', schema=schema)