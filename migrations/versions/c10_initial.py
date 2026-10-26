"""C10 initial — Unified Execution & Comparison Engine foundation.

Revision ID: c10_initial
Revises: <PREVIOUS_HEAD>
Create Date: 2025-01-01 00:00:00.000000

Creates the C10 foundation tables:
  - execution_configurations
  - execution_traces
  - execution_steps
  - execution_claims
  - comparison_experiments
  - comparison_runs
  - comparison_results
  - pricing_snapshots
  - budget_checkpoints
  - model_fingerprints
  - model_profiles
  - execution_profiles
  - model_connections
  - cost_ledger_entries
  - idempotency_keys

IMPORTANT: Replace `down_revision = "REPLACE_WITH_C9_HEAD"` below
with the actual previous head produced by `alembic heads` BEFORE
running `alembic upgrade head`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "c10_initial"
down_revision = "c9a1b2c3d4e5"  
branch_labels = None
depends_on = None


SCHEMA = "dsrt"


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # execution_configurations
    # -------------------------------------------------------------------------
    op.create_table(
        "execution_configurations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("organization_id", sa.String(64),
                  sa.ForeignKey(f"{SCHEMA}.organizations.id"), nullable=False),
        sa.Column("protocol", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("agent_slug", sa.String(255), nullable=False),
        sa.Column("agent_version", sa.String(64), nullable=False),
        sa.Column("agent_version_id", sa.String(64), nullable=False),
        sa.Column("model_fingerprint_id", sa.String(64), nullable=False),
        sa.Column("model_identifier", sa.String(255), nullable=False),
        sa.Column("provider_slug", sa.String(128), nullable=False),
        sa.Column("amplification_plan", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("max_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("max_model_calls", sa.Integer(), nullable=False),
        sa.Column("max_tool_calls", sa.Integer(), nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column("max_cost_usd", sa.Float(), nullable=True),
        sa.Column("pricing_snapshot_id", sa.String(64), nullable=False),
        sa.Column("context_profile_id", sa.String(64), nullable=True),
        sa.Column("tool_scopes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("world_slug", sa.String(255), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("top_p", sa.Float(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("configuration_hash", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("ix_c10_cfg_org_hash", "execution_configurations",
                    ["organization_id", "configuration_hash"], schema=SCHEMA)
    op.create_index("ix_c10_cfg_agent", "execution_configurations",
                    ["agent_slug", "agent_version"], schema=SCHEMA)

    # -------------------------------------------------------------------------
    # pricing_snapshots  (D8 — immutable, write-once)
    # -------------------------------------------------------------------------
    op.create_table(
        "pricing_snapshots",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("provider_slug", sa.String(128), nullable=False),
        sa.Column("model_identifier", sa.String(255), nullable=False),
        sa.Column("model_id", sa.String(64), nullable=True),
        sa.Column("provider_id", sa.String(64), nullable=True),
        sa.Column("input_price", sa.Float(), nullable=False),
        sa.Column("output_price", sa.Float(), nullable=False),
        sa.Column("cached_input_price", sa.Float(), nullable=True),
        sa.Column("reasoning_price", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("pricing_unit", sa.String(32), nullable=False,
                  server_default="per_1m_tokens"),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_document_hash", sa.String(128), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("captured_by", sa.String(128), nullable=True),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint("provider_slug", "model_identifier", "content_hash",
                            name="uq_c10_prs_dedup"),
        schema=SCHEMA,
    )
    op.create_index("ix_c10_prs_lookup", "pricing_snapshots",
                    ["provider_slug", "model_identifier", "effective_at"], schema=SCHEMA)
    op.create_index("ix_c10_prs_source", "pricing_snapshots", ["source"], schema=SCHEMA)

    # -------------------------------------------------------------------------
    # model_fingerprints
    # -------------------------------------------------------------------------
    op.create_table(
        "model_fingerprints",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("provider_slug", sa.String(128), nullable=False),
        sa.Column("model_identifier", sa.String(255), nullable=False),
        sa.Column("supports_tools", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("supports_vision", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("supports_audio", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("supports_streaming", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("supports_structured_output", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("supports_reasoning", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("context_window_tokens", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("input_modalities", sa.JSON(), nullable=False, server_default='["text"]'),
        sa.Column("output_modalities", sa.JSON(), nullable=False, server_default='["text"]'),
        sa.Column("fingerprint_hash", sa.String(128), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("fingerprint_hash", name="uq_c10_mfp_hash"),
        schema=SCHEMA,
    )
    op.create_index("ix_c10_mfp_provider_model", "model_fingerprints",
                    ["provider_slug", "model_identifier"], schema=SCHEMA)

    # -------------------------------------------------------------------------
    # model_profiles
    # -------------------------------------------------------------------------
    op.create_table(
        "model_profiles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("model_fingerprint_id", sa.String(64), nullable=False),
        sa.Column("tier", sa.String(32), nullable=False),
        sa.Column("median_latency_ms", sa.Integer(), nullable=True),
        sa.Column("p95_latency_ms", sa.Integer(), nullable=True),
        sa.Column("p99_latency_ms", sa.Integer(), nullable=True),
        sa.Column("median_output_tokens_per_second", sa.Float(), nullable=True),
        sa.Column("quality_markers", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("freshness", sa.String(32), nullable=False, server_default="FRESH"),
        sa.Column("reused_from_profile_id", sa.String(64), nullable=True),
        sa.Column("reuse_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("ix_c10_mpr_fp_tier", "model_profiles",
                    ["model_fingerprint_id", "tier"], schema=SCHEMA)

    # -------------------------------------------------------------------------
    # execution_profiles
    # -------------------------------------------------------------------------
    op.create_table(
        "execution_profiles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("model_fingerprint_id", sa.String(64), nullable=False),
        sa.Column("agent_slug", sa.String(255), nullable=False),
        sa.Column("agent_version", sa.String(64), nullable=False),
        sa.Column("task_class", sa.String(128), nullable=False),
        sa.Column("executions_observed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_rate", sa.Float(), nullable=True),
        sa.Column("median_cost_usd", sa.Float(), nullable=True),
        sa.Column("median_duration_seconds", sa.Float(), nullable=True),
        sa.Column("median_quality_score", sa.Float(), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.String(32), nullable=False, server_default="LOW"),
        sa.Column("freshness", sa.String(32), nullable=False, server_default="FRESH"),
        sa.Column("reused_from_profile_id", sa.String(64), nullable=True),
        sa.Column("reuse_reason", sa.Text(), nullable=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_c10_epr_lookup", "execution_profiles",
        ["organization_id", "model_fingerprint_id", "agent_slug", "task_class"],
        schema=SCHEMA,
    )

    # -------------------------------------------------------------------------
    # model_connections
    # -------------------------------------------------------------------------
    op.create_table(
        "model_connections",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("model_fingerprint_id", sa.String(64), nullable=False),
        sa.Column("credential_id", sa.String(64), nullable=False),
        sa.Column("endpoint_url", sa.Text(), nullable=True),
        sa.Column("region", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="UNKNOWN"),
        sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("credential_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_c10_mcn_lookup", "model_connections",
        ["organization_id", "model_fingerprint_id", "credential_id"],
        schema=SCHEMA,
    )

    # -------------------------------------------------------------------------
    # execution_traces
    # -------------------------------------------------------------------------
    op.create_table(
        "execution_traces",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("organization_id", sa.String(64),
                  sa.ForeignKey(f"{SCHEMA}.organizations.id"), nullable=False),
        sa.Column("configuration_id", sa.String(64),
                  sa.ForeignKey(f"{SCHEMA}.execution_configurations.id"), nullable=False),
        sa.Column("agent_slug", sa.String(255), nullable=False),
        sa.Column("agent_version_id", sa.String(64), nullable=False),
        sa.Column("model_fingerprint_id", sa.String(64), nullable=False),
        sa.Column("protocol", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("task_id", sa.String(64), nullable=True),
        sa.Column("c1_execution_id", sa.String(64), nullable=True),
        sa.Column("comparison_experiment_id", sa.String(64), nullable=True),
        sa.Column("comparison_run_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("worker_id", sa.String(128), nullable=True),
        sa.Column("worker_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("step_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_cached_input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_model_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tool_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("total_duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("artifact_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_metadata", sa.JSON(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("ix_c10_trace_org_status", "execution_traces",
                    ["organization_id", "status"], schema=SCHEMA)
    op.create_index("ix_c10_trace_config", "execution_traces", ["configuration_id"], schema=SCHEMA)
    op.create_index("ix_c10_trace_task", "execution_traces", ["task_id"], schema=SCHEMA)
    op.create_index("ix_c10_trace_c1_exe", "execution_traces", ["c1_execution_id"], schema=SCHEMA)
    op.create_index("ix_c10_trace_cmp_run", "execution_traces", ["comparison_run_id"], schema=SCHEMA)
    op.create_index("ix_c10_trace_worker", "execution_traces",
                    ["worker_id", "worker_heartbeat_at"], schema=SCHEMA)
    op.create_index(
        "ix_c10_trace_idempotency", "execution_traces",
        ["organization_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        schema=SCHEMA,
    )

    # -------------------------------------------------------------------------
    # execution_steps
    # -------------------------------------------------------------------------
    op.create_table(
        "execution_steps",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("execution_trace_id", sa.String(64),
                  sa.ForeignKey(f"{SCHEMA}.execution_traces.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("parent_step_id", sa.String(64), nullable=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("model_request_id", sa.String(64), nullable=True),
        sa.Column("tool_execution_id", sa.String(64), nullable=True),
        sa.Column("context_build_id", sa.String(64), nullable=True),
        sa.Column("verification_run_id", sa.String(64), nullable=True),
        sa.Column("amplification_stage_id", sa.String(64), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inputs_ref", sa.JSON(), nullable=True),
        sa.Column("outputs_ref", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("ix_c10_step_trace_idx", "execution_steps",
                    ["execution_trace_id", "step_index"], schema=SCHEMA)
    op.create_index("ix_c10_step_kind", "execution_steps", ["kind"], schema=SCHEMA)

    # -------------------------------------------------------------------------
    # execution_claims  (D10)
    # -------------------------------------------------------------------------
    op.create_table(
        "execution_claims",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("execution_trace_id", sa.String(64),
                  sa.ForeignKey(f"{SCHEMA}.execution_traces.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("step_id", sa.String(64), nullable=True),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("action_type", sa.String(64), nullable=False),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("evidence_level", sa.String(64), nullable=False),
        sa.Column("linked_tool_execution_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("linked_observation_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("linked_artifact_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("classification_rationale", sa.Text(), nullable=False),
        sa.Column("is_irreversible", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("requires_external_confirmation", sa.Boolean(), nullable=False,
                  server_default="false"),
        sa.Column("required_evidence_level", sa.String(64), nullable=False),
        sa.Column("classified_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("classified_by", sa.String(128), nullable=False,
                  server_default="dsrt.core.c10.classifier"),
        schema=SCHEMA,
    )
    op.create_index("ix_c10_claim_trace", "execution_claims",
                    ["execution_trace_id"], schema=SCHEMA)
    op.create_index("ix_c10_claim_classification", "execution_claims",
                    ["classification"], schema=SCHEMA)

    # -------------------------------------------------------------------------
    # comparison_experiments
    # -------------------------------------------------------------------------
    op.create_table(
        "comparison_experiments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("organization_id", sa.String(64),
                  sa.ForeignKey(f"{SCHEMA}.organizations.id"), nullable=False),
        sa.Column("user_id", sa.String(64),
                  sa.ForeignKey(f"{SCHEMA}.users.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("task_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("configuration_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("varied_dimensions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("controlled_dimensions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("measurement_dimensions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("min_runs_per_config", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("quality_tie_threshold", sa.Float(), nullable=False, server_default="0.02"),
        sa.Column("cost_savings_requires_quality", sa.Boolean(), nullable=False,
                  server_default="true"),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(64), nullable=True),
        sa.Column("outcome_rationale", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("ix_c10_cex_org_status", "comparison_experiments",
                    ["organization_id", "status"], schema=SCHEMA)

    # -------------------------------------------------------------------------
    # comparison_runs
    # -------------------------------------------------------------------------
    op.create_table(
        "comparison_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("comparison_experiment_id", sa.String(64),
                  sa.ForeignKey(f"{SCHEMA}.comparison_experiments.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("configuration_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("execution_trace_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(64), nullable=True),
        sa.Column("protocol_valid", sa.Boolean(), nullable=True),
        sa.Column("protocol_violations", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("run_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("ix_c10_crn_experiment", "comparison_runs",
                    ["comparison_experiment_id"], schema=SCHEMA)
    op.create_index("ix_c10_crn_status", "comparison_runs", ["status"], schema=SCHEMA)
    op.create_index("ix_c10_crn_task", "comparison_runs", ["task_id"], schema=SCHEMA)

    # -------------------------------------------------------------------------
    # comparison_results
    # -------------------------------------------------------------------------
    op.create_table(
        "comparison_results",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("comparison_run_id", sa.String(64),
                  sa.ForeignKey(f"{SCHEMA}.comparison_runs.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("comparison_experiment_id", sa.String(64), nullable=False),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(64), nullable=False),
        sa.Column("outcome_rationale", sa.Text(), nullable=False),
        sa.Column("dimensions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("leg_map", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("protocol_valid", sa.Boolean(), nullable=False),
        sa.Column("protocol_violations", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("cost_savings_valid", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("cost_savings_rationale", sa.Text(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("ix_c10_cmr_run", "comparison_results",
                    ["comparison_run_id"], schema=SCHEMA)
    op.create_index("ix_c10_cmr_experiment", "comparison_results",
                    ["comparison_experiment_id"], schema=SCHEMA)

    # -------------------------------------------------------------------------
    # budget_checkpoints
    # -------------------------------------------------------------------------
    op.create_table(
        "budget_checkpoints",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("execution_trace_id", sa.String(64),
                  sa.ForeignKey(f"{SCHEMA}.execution_traces.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("step_id", sa.String(64), nullable=True),
        sa.Column("checkpoint", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("projected_cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("projected_duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("projected_model_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("projected_tool_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("projected_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocking_dimension", sa.String(64), nullable=True),
        sa.Column("blocking_limit", sa.Float(), nullable=True),
        sa.Column("blocking_actual", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("ix_c10_bck_trace", "budget_checkpoints",
                    ["execution_trace_id"], schema=SCHEMA)
    op.create_index("ix_c10_bck_checkpoint_decision", "budget_checkpoints",
                    ["checkpoint", "decision"], schema=SCHEMA)

    # -------------------------------------------------------------------------
    # cost_ledger_entries  (append-only, INV-45)
    # -------------------------------------------------------------------------
    op.create_table(
        "cost_ledger_entries",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("execution_trace_id", sa.String(64),
                  sa.ForeignKey(f"{SCHEMA}.execution_traces.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("step_id", sa.String(64), nullable=True),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("amount_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("pricing_snapshot_id", sa.String(64), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_invocations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_model_request_id", sa.String(64), nullable=True),
        sa.Column("source_tool_execution_id", sa.String(64), nullable=True),
        sa.Column("source_verification_run_id", sa.String(64), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("ix_c10_cle_org_trace", "cost_ledger_entries",
                    ["organization_id", "execution_trace_id"], schema=SCHEMA)
    op.create_index("ix_c10_cle_category", "cost_ledger_entries",
                    ["category"], schema=SCHEMA)
    op.create_index("ix_c10_cle_recorded_at", "cost_ledger_entries",
                    ["recorded_at"], schema=SCHEMA)

    # -------------------------------------------------------------------------
    # idempotency_keys  (D5)
    # -------------------------------------------------------------------------
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("bound_resource_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "scope", "key",
                            name="uq_c10_idk_org_scope_key"),
        schema=SCHEMA,
    )
    op.create_index("ix_c10_idk_expires", "idempotency_keys",
                    ["expires_at"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("idempotency_keys", schema=SCHEMA)
    op.drop_table("cost_ledger_entries", schema=SCHEMA)
    op.drop_table("budget_checkpoints", schema=SCHEMA)
    op.drop_table("comparison_results", schema=SCHEMA)
    op.drop_table("comparison_runs", schema=SCHEMA)
    op.drop_table("comparison_experiments", schema=SCHEMA)
    op.drop_table("execution_claims", schema=SCHEMA)
    op.drop_table("execution_steps", schema=SCHEMA)
    op.drop_table("execution_traces", schema=SCHEMA)
    op.drop_table("model_connections", schema=SCHEMA)
    op.drop_table("execution_profiles", schema=SCHEMA)
    op.drop_table("model_profiles", schema=SCHEMA)
    op.drop_table("model_fingerprints", schema=SCHEMA)
    op.drop_table("pricing_snapshots", schema=SCHEMA)
    op.drop_table("execution_configurations", schema=SCHEMA)