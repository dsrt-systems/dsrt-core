# migrations/versions/c9a1b2c3d4e5_c9_routing_tables.py
"""c9 routing tables

Revision ID: c9a1b2c3d4e5
Revises: d56328795f13
Create Date: 2025-01-15 00:00:00.000000+00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "c9a1b2c3d4e5"
down_revision = "d56328795f13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. routing_policies ────────────────────────────────────────
    op.create_table(
        "routing_policies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(255), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("version", sa.String(32), nullable=False, server_default="1"),
        sa.Column("constraints", JSONB, nullable=True),
        sa.Column("preferences", JSONB, nullable=True),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="dsrt",
    )
    op.create_index(
        "ix_routing_policies_tenant",
        "routing_policies",
        ["tenant_id"],
        schema="dsrt",
    )
    op.create_index(
        "ix_routing_policies_name",
        "routing_policies",
        ["name"],
        schema="dsrt",
    )

    # ── 2. routing_profiles ────────────────────────────────────────
    op.create_table(
        "routing_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(255), nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "quality_priority",
            sa.String(16),
            nullable=False,
            server_default="MEDIUM",
        ),
        sa.Column(
            "cost_priority",
            sa.String(16),
            nullable=False,
            server_default="MEDIUM",
        ),
        sa.Column(
            "latency_priority",
            sa.String(16),
            nullable=False,
            server_default="MEDIUM",
        ),
        sa.Column(
            "reliability_priority",
            sa.String(16),
            nullable=False,
            server_default="MEDIUM",
        ),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "is_builtin", sa.Boolean, nullable=False, server_default="false"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="dsrt",
    )
    op.create_index(
        "ix_routing_profiles_tenant",
        "routing_profiles",
        ["tenant_id"],
        schema="dsrt",
    )
    op.create_unique_constraint(
        "uq_routing_profiles_name_tenant",
        "routing_profiles",
        ["name", "tenant_id"],
        schema="dsrt",
    )

    # ── 3. route_decisions ─────────────────────────────────────────
    op.create_table(
        "route_decisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", sa.String(255), nullable=False),
        sa.Column("execution_id", sa.String(255), nullable=True),
        sa.Column(
            "routing_policy_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "dsrt.routing_policies.id", ondelete="SET NULL"
            ),
            nullable=True,
        ),
        sa.Column(
            "routing_profile_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "dsrt.routing_profiles.id", ondelete="SET NULL"
            ),
            nullable=True,
        ),
        sa.Column("selected_agent_version_id", sa.String(255), nullable=True),
        sa.Column("selected_model_version_id", sa.String(255), nullable=True),
        sa.Column("selected_world_version_id", sa.String(255), nullable=True),
        sa.Column("selected_tools", JSONB, nullable=True),
        sa.Column(
            "candidate_count", sa.Integer, nullable=False, server_default="0"
        ),
        sa.Column(
            "candidates_eligible",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column("decision_reason", JSONB, nullable=True),
        sa.Column("evidence_refs", JSONB, nullable=True),
        sa.Column("configuration_hash", sa.String(128), nullable=True),
        sa.Column(
            "status", sa.String(32), nullable=False, server_default="PENDING"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="dsrt",
    )
    op.create_index(
        "ix_route_decisions_task",
        "route_decisions",
        ["task_id"],
        schema="dsrt",
    )
    op.create_index(
        "ix_route_decisions_execution",
        "route_decisions",
        ["execution_id"],
        schema="dsrt",
    )
    op.create_index(
        "ix_route_decisions_status",
        "route_decisions",
        ["status"],
        schema="dsrt",
    )
    op.create_index(
        "ix_route_decisions_created",
        "route_decisions",
        ["created_at"],
        schema="dsrt",
    )

    # ── 4. route_candidates ────────────────────────────────────────
    op.create_table(
        "route_candidates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "route_decision_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "dsrt.route_decisions.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column("agent_version_id", sa.String(255), nullable=False),
        sa.Column("model_version_id", sa.String(255), nullable=False),
        sa.Column("world_version_id", sa.String(255), nullable=True),
        sa.Column("tools", JSONB, nullable=True),
        sa.Column(
            "eligibility_status",
            sa.String(16),
            nullable=False,
            server_default="ELIGIBLE",
        ),
        sa.Column("rejection_reason", JSONB, nullable=True),
        sa.Column("capability_fit", JSONB, nullable=True),
        sa.Column("constraint_fit", JSONB, nullable=True),
        sa.Column("evidence_summary", JSONB, nullable=True),
        sa.Column("evaluation_scores", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="dsrt",
    )
    op.create_index(
        "ix_route_candidates_decision",
        "route_candidates",
        ["route_decision_id"],
        schema="dsrt",
    )
    op.create_index(
        "ix_route_candidates_eligibility",
        "route_candidates",
        ["eligibility_status"],
        schema="dsrt",
    )

    # ── 5. routing_evidence ────────────────────────────────────────
    op.create_table(
        "routing_evidence",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("benchmark_id", sa.String(255), nullable=True),
        sa.Column("benchmark_version", sa.String(64), nullable=True),
        sa.Column("agent_version", sa.String(255), nullable=True),
        sa.Column("model_version", sa.String(255), nullable=True),
        sa.Column("world_version", sa.String(255), nullable=True),
        sa.Column(
            "sample_count", sa.Integer, nullable=False, server_default="0"
        ),
        sa.Column("metrics", JSONB, nullable=True),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="dsrt",
    )
    op.create_index(
        "ix_routing_evidence_source",
        "routing_evidence",
        ["source_type"],
        schema="dsrt",
    )
    op.create_index(
        "ix_routing_evidence_model",
        "routing_evidence",
        ["model_version"],
        schema="dsrt",
    )
    op.create_index(
        "ix_routing_evidence_benchmark",
        "routing_evidence",
        ["benchmark_id"],
        schema="dsrt",
    )
    op.create_index(
        "ix_routing_evidence_observed",
        "routing_evidence",
        ["observed_at"],
        schema="dsrt",
    )

    # ── 6. fallback_policies ───────────────────────────────────────
    op.create_table(
        "fallback_policies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(255), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("triggers", JSONB, nullable=True),
        sa.Column(
            "action_type",
            sa.String(32),
            nullable=False,
            server_default="RETRY",
        ),
        sa.Column("candidates", JSONB, nullable=True),
        sa.Column(
            "max_attempts", sa.Integer, nullable=False, server_default="3"
        ),
        sa.Column(
            "backoff_seconds", sa.Float, nullable=False, server_default="1.0"
        ),
        sa.Column(
            "is_active", sa.Boolean, nullable=False, server_default="true"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="dsrt",
    )
    op.create_index(
        "ix_fallback_policies_tenant",
        "fallback_policies",
        ["tenant_id"],
        schema="dsrt",
    )

    # ── 7. provider_health ─────────────────────────────────────────
    op.create_table(
        "provider_health",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column(
            "status", sa.String(32), nullable=False, server_default="UNKNOWN"
        ),
        sa.Column("latency_p50_ms", sa.Float, nullable=True),
        sa.Column("latency_p99_ms", sa.Float, nullable=True),
        sa.Column("error_rate", sa.Float, nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="dsrt",
    )
    op.create_index(
        "ix_provider_health_provider",
        "provider_health",
        ["provider_id"],
        schema="dsrt",
    )
    op.create_index(
        "ix_provider_health_status",
        "provider_health",
        ["status"],
        schema="dsrt",
    )
    op.create_index(
        "ix_provider_health_expires",
        "provider_health",
        ["expires_at"],
        schema="dsrt",
    )

    # ── 8. route_cache ─────────────────────────────────────────────
    op.create_table(
        "route_cache",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("cache_key_hash", sa.String(128), nullable=False),
        sa.Column("requirements_hash", sa.String(128), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("profile_id", sa.String(255), nullable=True),
        sa.Column("provider_health_hash", sa.String(64), nullable=False),
        sa.Column(
            "route_decision_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "dsrt.route_decisions.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        schema="dsrt",
    )
    op.create_unique_constraint(
        "uq_route_cache_key",
        "route_cache",
        ["cache_key_hash"],
        schema="dsrt",
    )
    op.create_index(
        "ix_route_cache_expires",
        "route_cache",
        ["expires_at"],
        schema="dsrt",
    )


def downgrade() -> None:
    op.drop_table("route_cache", schema="dsrt")
    op.drop_table("provider_health", schema="dsrt")
    op.drop_table("fallback_policies", schema="dsrt")
    op.drop_table("routing_evidence", schema="dsrt")
    op.drop_table("route_candidates", schema="dsrt")
    op.drop_table("route_decisions", schema="dsrt")
    op.drop_table("routing_profiles", schema="dsrt")
    op.drop_table("routing_policies", schema="dsrt")