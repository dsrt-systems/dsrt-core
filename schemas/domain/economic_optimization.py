"""
C11.5 — Economic Optimization Engine domain schemas.

Defines the cost model, constraint system, optimization policies,
execution configuration comparison, and budget-aware plan generation.

Central objective:
    min_θ E[C(θ)]  s.t.  Q(θ)≥Q_min, R(θ)≥R_min, L(θ)≤L_max, C(θ)≤B
"""

from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class OptimizationPolicy(str, enum.Enum):
    """Three standard optimization policies per spec §6C."""
    ECONOMY = "economy"
    BALANCED = "balanced"
    QUALITY = "quality"


class FeasibilityStatus(str, enum.Enum):
    """Whether a candidate configuration satisfies all hard constraints."""
    FEASIBLE = "feasible"
    INFEASIBLE_QUALITY = "infeasible_quality"
    INFEASIBLE_RELIABILITY = "infeasible_reliability"
    INFEASIBLE_LATENCY = "infeasible_latency"
    INFEASIBLE_BUDGET = "infeasible_budget"
    INFEASIBLE_MULTIPLE = "infeasible_multiple"
    UNKNOWN = "unknown"


class PlanStatus(str, enum.Enum):
    """Lifecycle of an optimization plan."""
    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Cost breakdown
# ---------------------------------------------------------------------------

class CostBreakdown(BaseModel):
    """
    Total execution cost decomposed per spec §6A:
        C_total = C_model + C_planning + C_retrieval + C_tools
                  + C_environment + C_verification + C_recovery
    """
    model_cost: float = Field(0.0, ge=0.0, description="Inference cost for primary model calls")
    planning_cost: float = Field(0.0, ge=0.0, description="Orchestration / decomposition calls")
    retrieval_cost: float = Field(0.0, ge=0.0, description="Context retrieval and compilation")
    tool_cost: float = Field(0.0, ge=0.0, description="Tool and API invocation costs")
    environment_cost: float = Field(0.0, ge=0.0, description="Browser, compute, sandbox runtime")
    verification_cost: float = Field(0.0, ge=0.0, description="Verification step costs")
    recovery_cost: float = Field(0.0, ge=0.0, description="Expected retry / repair / escalation costs")

    @property
    def total(self) -> float:
        return (
            self.model_cost
            + self.planning_cost
            + self.retrieval_cost
            + self.tool_cost
            + self.environment_cost
            + self.verification_cost
            + self.recovery_cost
        )


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------

class OptimizationConstraints(BaseModel):
    """Hard constraints that every feasible configuration must satisfy."""
    min_quality: float = Field(0.0, ge=0.0, le=1.0, description="Q_min")
    min_reliability: float = Field(0.0, ge=0.0, le=1.0, description="R_min")
    max_latency_ms: int | None = Field(None, ge=0, description="L_max (None = unconstrained)")
    max_budget: float | None = Field(None, ge=0.0, description="B (None = unconstrained)")
    max_model_calls: int | None = Field(None, ge=1)
    max_retries: int | None = Field(None, ge=0)
    max_parallel_subtasks: int | None = Field(None, ge=1)
    max_environment_runtime_ms: int | None = Field(None, ge=0)
    max_verification_cost: float | None = Field(None, ge=0.0)
    max_escalation_cost: float | None = Field(None, ge=0.0)


# ---------------------------------------------------------------------------
# Execution configuration candidate
# ---------------------------------------------------------------------------

class ExecutionConfigCandidate(BaseModel):
    """
    A fully specified execution configuration to be evaluated.
    Produced by combining C11.3 model selection + C11.4 strategy plan.
    """
    candidate_id: str
    model_fingerprint: str
    model_display_name: str = ""
    connection_id: str = ""
    agent_id: str | None = None
    agent_version: str | None = None
    strategies: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    environments: list[str] = Field(default_factory=list)
    verification_level: str = "V1"

    # Performance estimates from C11.2/C11.3
    estimated_quality: float | None = None
    estimated_reliability: float | None = None
    estimated_latency_ms: int | None = None
    evidence_sample_size: int = 0
    evidence_confidence: float | None = None

    # Cost estimates
    cost_breakdown: CostBreakdown = Field(default_factory=CostBreakdown)

    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Feasibility result for a single candidate
# ---------------------------------------------------------------------------

class CandidateFeasibility(BaseModel):
    """Result of checking one candidate against hard constraints."""
    candidate_id: str
    status: FeasibilityStatus
    violations: list[str] = Field(default_factory=list)
    satisfied_constraints: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Scored & ranked candidate
# ---------------------------------------------------------------------------

class ScoredCandidate(BaseModel):
    """A feasible candidate with a composite objective score."""
    candidate_id: str
    feasibility: CandidateFeasibility
    objective_score: float = Field(
        0.0,
        description="Composite score: higher is better (policy-weighted)"
    )
    quality_score: float = 0.0
    reliability_score: float = 0.0
    cost_score: float = 0.0
    latency_score: float = 0.0
    evidence_penalty: float = Field(
        0.0,
        description="Penalty applied for low evidence confidence"
    )
    score_components: dict[str, float] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Budget execution limits
# ---------------------------------------------------------------------------

class BudgetExecutionLimits(BaseModel):
    """Concrete limits sent to C10 for enforcement (spec §6E)."""
    max_model_calls: int = 50
    max_retries: int = 3
    max_parallel_subtasks: int = 4
    max_environment_runtime_ms: int = 300_000
    max_verification_cost: float = 0.0
    max_escalation_cost: float = 0.0
    total_authorized_cost: float = 0.0


# ---------------------------------------------------------------------------
# Optimization plan (the core output)
# ---------------------------------------------------------------------------

class OptimizationPlanOutput(BaseModel):
    """
    Frozen, versioned optimization plan per spec §12.2.
    Once approved, C10 executes this exact configuration.
    """
    optimization_id: str
    plan_version: str = "1"
    task_profile_id: str = ""
    workspace_id: str = ""

    # Selected configuration
    selected_candidate: ExecutionConfigCandidate
    alternatives: list[ScoredCandidate] = Field(default_factory=list)

    # Estimates
    estimated_quality: float | None = None
    estimated_reliability: float | None = None
    estimated_cost: float | None = None
    estimated_latency_ms: int | None = None

    # Budget
    authorized_budget: float | None = None
    budget_limits: BudgetExecutionLimits = Field(default_factory=BudgetExecutionLimits)

    # Decision audit
    optimization_policy: OptimizationPolicy = OptimizationPolicy.BALANCED
    constraints: OptimizationConstraints = Field(default_factory=OptimizationConstraints)
    decision_reasons: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    # Lifecycle
    approval_required: bool = False
    status: PlanStatus = PlanStatus.DRAFT


# ---------------------------------------------------------------------------
# Prediction record (for later accuracy analysis)
# ---------------------------------------------------------------------------

class PredictionRecord(BaseModel):
    """Stores C11.5 predictions so C11.8 can compare with actuals."""
    optimization_id: str
    candidate_id: str
    predicted_quality: float | None = None
    predicted_reliability: float | None = None
    predicted_cost: float | None = None
    predicted_latency_ms: int | None = None
    evidence_confidence: float | None = None
    actual_quality: float | None = None
    actual_reliability: float | None = None
    actual_cost: float | None = None
    actual_latency_ms: int | None = None