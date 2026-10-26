"""
DSRT C10 Budget & Cost Ledger Contracts (C10 §8, INV-38, INV-45).

Six-checkpoint budget enforcement:
  PRE_ADMISSION   — before trace is admitted
  POST_ROUTING    — after model resolution, before any call
  PRE_MODEL_CALL  — before each model request
  POST_MODEL_CALL — after each model request (reconcile actuals)
  PRE_TOOL_CALL   — before each tool invocation
  POST_TOOL_CALL  — after each tool invocation

Each checkpoint can ALLOW, SOFT_BLOCK (warn), or HARD_BLOCK (abort).

The CostLedger subscribes to C2 UsageMeter and adds non-model costs:
tool execution, environment provisioning, verification, recovery.
Total cost (INV-45) = model + planning + tools + env + verification + recovery.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field

from schemas.domain.base import DSRTImmutableSchema, DSRTSchema, TimestampedSchema


class BudgetCheckpoint(str, Enum):
    """The six budget enforcement checkpoints (INV-38)."""
    PRE_ADMISSION = "PRE_ADMISSION"
    POST_ROUTING = "POST_ROUTING"
    PRE_MODEL_CALL = "PRE_MODEL_CALL"
    POST_MODEL_CALL = "POST_MODEL_CALL"
    PRE_TOOL_CALL = "PRE_TOOL_CALL"
    POST_TOOL_CALL = "POST_TOOL_CALL"


class BudgetDecision(str, Enum):
    ALLOW = "ALLOW"
    SOFT_BLOCK = "SOFT_BLOCK"     # Warn but proceed
    HARD_BLOCK = "HARD_BLOCK"     # Abort execution


class BudgetDimension(str, Enum):
    COST_USD = "cost_usd"
    DURATION_SECONDS = "duration_seconds"
    MODEL_CALLS = "model_calls"
    TOOL_CALLS = "tool_calls"
    TOKENS = "tokens"


class CostCategory(str, Enum):
    """Cost category decomposition (INV-45)."""
    MODEL = "MODEL"
    PLANNING = "PLANNING"          # Amplification planning stage
    TOOL = "TOOL"
    ENVIRONMENT = "ENVIRONMENT"
    VERIFICATION = "VERIFICATION"
    RECOVERY = "RECOVERY"
    OVERHEAD = "OVERHEAD"


# =============================================================================
# Budget Check (per-call evaluation record)
# =============================================================================


class BudgetGuardResult(DSRTSchema):
    """Result of a single budget checkpoint evaluation."""
    checkpoint: BudgetCheckpoint
    decision: BudgetDecision
    rationale: str

    # Per-dimension evaluation at the time of check
    projected_cost_usd: float
    projected_duration_seconds: int
    projected_model_calls: int
    projected_tool_calls: int
    projected_tokens: int

    # Which dimension triggered the block, if any
    blocking_dimension: BudgetDimension | None = None
    blocking_limit: float | None = None
    blocking_actual: float | None = None

    evaluated_at: datetime


class BudgetCheckpointRecord(TimestampedSchema):
    """Persisted record of a budget checkpoint evaluation."""
    id: str
    execution_trace_id: str
    step_id: str | None = None

    checkpoint: BudgetCheckpoint
    decision: BudgetDecision
    rationale: str

    projected_cost_usd: float
    projected_duration_seconds: int
    projected_model_calls: int
    projected_tool_calls: int
    projected_tokens: int

    blocking_dimension: BudgetDimension | None = None
    blocking_limit: float | None = None
    blocking_actual: float | None = None


# =============================================================================
# Cost Ledger (INV-45)
# =============================================================================


class CostLedgerEntry(DSRTImmutableSchema):
    """Immutable cost ledger entry (INV-45).

    Append-only. Every unit of billable work in a C10 execution
    produces exactly one ledger entry. Summing entries by trace_id
    yields the authoritative total cost.
    """
    id: str
    organization_id: str
    execution_trace_id: str
    step_id: str | None = None

    category: CostCategory

    # Monetary
    amount_usd: float
    pricing_snapshot_id: str | None = None  # NULL for non-model categories

    # Quantities (for audit)
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    tool_invocations: int = 0
    duration_ms: int = 0

    # Provenance
    source_model_request_id: str | None = None
    source_tool_execution_id: str | None = None
    source_verification_run_id: str | None = None

    description: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    recorded_at: datetime


class CostLedgerEntryCreate(DSRTSchema):
    organization_id: str
    execution_trace_id: str
    step_id: str | None = None
    category: CostCategory
    amount_usd: float
    pricing_snapshot_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    tool_invocations: int = 0
    duration_ms: int = 0
    source_model_request_id: str | None = None
    source_tool_execution_id: str | None = None
    source_verification_run_id: str | None = None
    description: str
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Idempotency keys (D5)
# =============================================================================


class IdempotencyKeyRecord(TimestampedSchema):
    """Persisted idempotency key used to deduplicate execution requests."""
    id: str
    organization_id: str
    scope: str  # e.g. "execution", "comparison_run"
    key: str
    bound_resource_id: str  # The resource this key resolved to
    created_at: datetime
    expires_at: datetime | None = None