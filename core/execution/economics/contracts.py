"""
Economics contracts — shared schemas for cost accounting.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CostCategory(str, Enum):
    """All cost components tracked by the ledger (spec §8)."""

    MODEL_INFERENCE = "MODEL_INFERENCE"
    HOSTED_INFERENCE = "HOSTED_INFERENCE"
    PLANNING = "PLANNING"
    RETRIEVAL = "RETRIEVAL"
    TOOLS = "TOOLS"
    ENVIRONMENT = "ENVIRONMENT"
    VERIFICATION = "VERIFICATION"
    RECOVERY = "RECOVERY"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    OTHER = "OTHER"


class CostAvailability(str, Enum):
    """
    How reliable the recorded cost is.

    ACTUAL      — provider-reported or precisely metered
    ESTIMATED   — derived from pricing snapshot × usage
    UNAVAILABLE — known to have occurred but no price/usage available
    """

    ACTUAL = "ACTUAL"
    ESTIMATED = "ESTIMATED"
    UNAVAILABLE = "UNAVAILABLE"


class BudgetDecision(str, Enum):
    ALLOW = "ALLOW"
    WARN = "WARN"
    DENY = "DENY"


class BudgetScope(str, Enum):
    EXECUTION = "EXECUTION"
    EXPERIMENT = "EXPERIMENT"
    WORKSPACE = "WORKSPACE"
    OPERATION = "OPERATION"  # single model call / tool call


# ---------------------------------------------------------------------------
# Cost entry
# ---------------------------------------------------------------------------

class CostEntry(BaseModel):
    """
    One attributable cost line.

    Every entry MUST link to an execution_id. Optional experiment/run
    linkage supports paired comparisons. Credentials never appear here.
    """

    entry_id: str = Field(default_factory=lambda: str(uuid4()))
    execution_id: str
    workspace_id: str
    experiment_id: str | None = None
    run_id: str | None = None
    step_id: str | None = None

    category: CostCategory
    availability: CostAvailability

    # Money
    amount_usd: float | None = None  # None when UNAVAILABLE
    currency: str = "USD"

    # Usage that produced the cost (when applicable)
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    quantity: float = 1.0  # generic units (tool calls, GB-seconds, etc.)
    unit_label: str | None = None

    # Pricing provenance
    pricing_snapshot_id: str | None = None
    provider: str | None = None
    model_id: str | None = None
    model_fingerprint_hash: str | None = None

    # Operation context
    operation: str = ""  # e.g. "chat.completions", "tool.shell", "verify.schema"
    idempotency_key: str | None = None
    description: str = ""

    # Flags
    is_retry: bool = False
    is_repair: bool = False

    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def billable_amount_usd(self) -> float:
        """Amount included in totals; UNAVAILABLE contributes 0 but is tracked."""
        if self.availability == CostAvailability.UNAVAILABLE:
            return 0.0
        return float(self.amount_usd or 0.0)


# ---------------------------------------------------------------------------
# Breakdown & summary
# ---------------------------------------------------------------------------

class CategoryAmount(BaseModel):
    category: CostCategory
    actual_usd: float = 0.0
    estimated_usd: float = 0.0
    unavailable_count: int = 0
    entry_count: int = 0

    @property
    def known_usd(self) -> float:
        return self.actual_usd + self.estimated_usd


class CostBreakdown(BaseModel):
    """Aggregated cost view for one execution / experiment / path."""

    execution_id: str | None = None
    experiment_id: str | None = None
    run_id: str | None = None

    total_actual_usd: float = 0.0
    total_estimated_usd: float = 0.0
    total_known_usd: float = 0.0
    unavailable_entry_count: int = 0
    entry_count: int = 0

    by_category: dict[str, CategoryAmount] = Field(default_factory=dict)

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cached_tokens: int = 0

    has_unavailable_costs: bool = False
    notes: list[str] = Field(default_factory=list)


class EconomicsSummary(BaseModel):
    """High-level economics snapshot for APIs / UI."""

    subject_type: str  # execution | experiment | comparison
    subject_id: str
    breakdown: CostBreakdown
    cost_per_attempt_usd: float | None = None
    cost_per_successful_task_usd: float | None = None
    successful_tasks: int = 0
    attempts: int = 0
    budget_limit_usd: float | None = None
    budget_remaining_usd: float | None = None
    budget_utilized_ratio: float | None = None


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

class BudgetDefinition(BaseModel):
    """
    Multi-level budget envelope.

    Enforcement happens before costly operations, not after.
    """

    budget_id: str = Field(default_factory=lambda: str(uuid4()))
    scope: BudgetScope = BudgetScope.EXECUTION
    scope_id: str = ""  # execution_id / experiment_id / workspace_id

    limit_usd: float
    warn_threshold_ratio: float = 0.8  # warn at 80%
    hard_limit: bool = True  # DENY when exceeded if True; WARN-only if False

    # Optional per-operation caps
    max_single_model_call_usd: float | None = None
    max_single_tool_call_usd: float | None = None
    max_repair_usd: float | None = None

    allow_estimated_enforcement: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class BudgetCheckResult(BaseModel):
    """Outcome of a pre-operation budget check."""

    decision: BudgetDecision
    budget_id: str
    scope: BudgetScope
    limit_usd: float
    spent_usd: float
    pending_usd: float
    projected_usd: float
    remaining_usd: float
    warn_threshold_usd: float
    reason: str = ""
    category: CostCategory | None = None
    operation: str = ""
    checked_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )