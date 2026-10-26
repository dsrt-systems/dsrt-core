"""
Domain schemas for C11.9 Governance, Policy Enforcement, and Optimization Plans.

Pure Pydantic schemas only. ORM models live in:
  core/storage/models/optimization_c11_governance.py
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PolicyEnforcementLevel(str, Enum):
    """How strictly a policy is applied."""

    ADVISORY = "advisory"
    STRICT = "strict"
    MANDATORY = "mandatory"


class LearningCandidateStatus(str, Enum):
    """Lifecycle status for learning / promotion candidates."""

    PROPOSED = "proposed"
    UNDER_REVIEW = "under_review"
    VALIDATING = "validating"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"
    EXPIRED = "expired"


class FallbackMode(str, Enum):
    """Circuit-breaker / fallback operating mode."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    MAINTENANCE = "maintenance"


class DecisionType(str, Enum):
    """Types of optimization decisions recorded for audit."""

    MODEL_SELECTION = "model_selection"
    STRATEGY_SELECTION = "strategy_selection"
    AGENT_SELECTION = "agent_selection"
    VERIFICATION_PLAN = "verification_plan"
    BUDGET_ALLOCATION = "budget_allocation"
    FALLBACK = "fallback"
    POLICY_OVERRIDE = "policy_override"
    ESCALATION = "escalation"


class OptimizationMode(str, Enum):
    ECONOMY = "economy"
    BALANCED = "balanced"
    QUALITY = "quality"
    CUSTOM = "custom"


# ---------------------------------------------------------------------------
# Policy / compliance
# ---------------------------------------------------------------------------

class PolicyViolation(BaseModel):
    """Single policy violation discovered during compliance checks."""

    model_config = ConfigDict(extra="ignore")

    policy_id: Optional[str] = None
    violation_type: str
    severity: str = "warning"  # warning | error | critical
    message: str
    requires_approval: bool = False
    field_name: Optional[str] = None
    actual_value: Optional[Any] = None
    expected_value: Optional[Any] = None
    created_at: datetime = Field(default_factory=_utc_now)


class GovernanceViolation(PolicyViolation):
    """Alias-compatible governance violation (same shape as PolicyViolation)."""

    pass


class PolicyCheckResult(BaseModel):
    """Outcome of validating a request or selection against a policy."""

    model_config = ConfigDict(extra="ignore")

    is_compliant: bool = True
    policy_id: Optional[str] = None
    violations: List[PolicyViolation] = Field(default_factory=list)
    enforcement_level: Optional[PolicyEnforcementLevel] = None
    approval_required: bool = False
    blocking: bool = False


class PolicyEvaluationResult(BaseModel):
    """Broader evaluation wrapper used by higher-level governance flows."""

    model_config = ConfigDict(extra="ignore")

    evaluation_id: str = Field(default_factory=lambda: _new_id("eval"))
    is_compliant: bool = True
    policy_id: Optional[str] = None
    checks: List[PolicyCheckResult] = Field(default_factory=list)
    violations: List[PolicyViolation] = Field(default_factory=list)
    enforcement_level: Optional[PolicyEnforcementLevel] = None
    approval_required: bool = False
    blocking: bool = False
    notes: List[str] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=_utc_now)


class ComplianceCheck(BaseModel):
    """Individual named compliance check record."""

    model_config = ConfigDict(extra="ignore")

    check_id: str = Field(default_factory=lambda: _new_id("chk"))
    check_name: str
    passed: bool = True
    severity: str = "info"
    message: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class GovernanceRule(BaseModel):
    """Generic governance rule definition."""

    model_config = ConfigDict(extra="ignore")

    rule_id: str = Field(default_factory=lambda: _new_id("rule"))
    name: str
    description: str = ""
    rule_type: str = "policy"
    severity: str = "error"
    enabled: bool = True
    conditions: Dict[str, Any] = Field(default_factory=dict)
    actions: Dict[str, Any] = Field(default_factory=dict)


class OptimizationPolicy(BaseModel):
    """
    Tenant/user optimization policy.

    Field names match OptimizationPolicyModel and PolicyEnforcer._model_to_schema.
    """

    model_config = ConfigDict(extra="ignore", use_enum_values=False)

    policy_id: str = Field(default_factory=lambda: _new_id("pol"))
    organization_id: str
    user_id: Optional[str] = None
    policy_name: str = "default"
    version: int = 1
    optimization_mode: str = "balanced"
    preferred_models: List[str] = Field(default_factory=list)
    allowed_models: List[str] = Field(default_factory=list)
    forbidden_models: List[str] = Field(default_factory=list)
    model_selection_lock: str = "automatic"  # automatic | fixed | preferred
    preferred_agents: List[str] = Field(default_factory=list)
    allowed_agents: List[str] = Field(default_factory=list)
    max_cost_usd_per_task: Optional[float] = None
    max_latency_ms_per_task: Optional[float] = None
    min_quality_score: float = 0.70
    min_reliability_score: float = 0.80
    allow_model_escalation: bool = True
    allow_strategy_adaptation: bool = True
    require_mandatory_security_checks: bool = True
    approval_required_for_budget_override: bool = True
    approval_required_for_model_change: bool = False
    approval_required_for_sensitive_tools: bool = True
    enforcement_level: PolicyEnforcementLevel = PolicyEnforcementLevel.STRICT
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    active: bool = True


# Backward-compatible alias used in some modules / docs
GovernancePolicy = OptimizationPolicy


# ---------------------------------------------------------------------------
# Optimization request / plan / decision / snapshot
# ---------------------------------------------------------------------------

class OptimizationRequest(BaseModel):
    """
    Optimization request.

    Supports both C11.9 field names (organization_id, task_description, max_cost)
    and C11.10/API aliases (tenant_id, prompt, max_budget_usd).
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    request_id: str = Field(default_factory=lambda: _new_id("req"))
    organization_id: str = "default-org"
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    task_id: str = Field(default_factory=lambda: _new_id("task"))
    task_description: str = ""
    prompt: Optional[str] = None
    optimization_mode: str = "balanced"
    model_preference: str = "automatic"
    agent_preference: Optional[str] = None
    max_cost: Optional[float] = None
    max_budget_usd: Optional[float] = None
    max_latency_ms: Optional[float] = None
    allow_model_escalation: bool = True
    allow_strategy_adaptation: bool = True
    preferred_strategies: List[str] = Field(default_factory=list)
    context: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def _sync_aliased_fields(self) -> "OptimizationRequest":
        # tenant_id <-> organization_id
        if self.tenant_id and (
            not self.organization_id or self.organization_id == "default-org"
        ):
            object.__setattr__(self, "organization_id", self.tenant_id)
        if not self.tenant_id and self.organization_id:
            object.__setattr__(self, "tenant_id", self.organization_id)

        # prompt <-> task_description
        if self.prompt and not self.task_description:
            object.__setattr__(self, "task_description", self.prompt)
        if self.task_description and not self.prompt:
            object.__setattr__(self, "prompt", self.task_description)

        # max_budget_usd <-> max_cost
        if self.max_budget_usd is not None and self.max_cost is None:
            object.__setattr__(self, "max_cost", self.max_budget_usd)
        if self.max_cost is not None and self.max_budget_usd is None:
            object.__setattr__(self, "max_budget_usd", self.max_cost)

        return self


class OptimizationDecision(BaseModel):
    """Auditable optimization decision record (Pydantic side)."""

    model_config = ConfigDict(extra="ignore", use_enum_values=False)

    decision_id: str = Field(default_factory=lambda: _new_id("dec"))
    optimization_id: str = ""
    task_id: str = ""
    organization_id: str = ""
    decision_type: Union[DecisionType, str] = DecisionType.MODEL_SELECTION
    decision_subject: str = ""
    chosen_option: str = ""
    rejected_options: List[str] = Field(default_factory=list)
    decision_reasons: List[str] = Field(default_factory=list)
    evidence_references: List[Any] = Field(default_factory=list)
    policy_id: Optional[str] = None
    confidence_score: float = 1.0
    created_at: datetime = Field(default_factory=_utc_now)


class OptimizationSnapshot(BaseModel):
    """Point-in-time snapshot of an approved/ready optimization plan."""

    model_config = ConfigDict(extra="ignore")

    snapshot_id: str = Field(default_factory=lambda: _new_id("snap"))
    optimization_id: str
    task_id: str
    organization_id: str
    plan_version: int = 1
    task_profile_json: Dict[str, Any] = Field(default_factory=dict)
    selected_model: str = ""
    selected_agent: Optional[str] = None
    selected_strategies: List[str] = Field(default_factory=list)
    verification_plan_json: Dict[str, Any] = Field(default_factory=dict)
    policy_snapshot_json: Dict[str, Any] = Field(default_factory=dict)
    evidence_snapshot_json: Dict[str, Any] = Field(default_factory=dict)
    estimated_cost: float = 0.0
    estimated_latency_ms: float = 0.0
    estimated_quality: float = 0.0
    approved_by: Optional[str] = None
    approval_timestamp: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_utc_now)


class OptimizationPlanV2(BaseModel):
    """
    Full optimization plan returned by MasterOptimizationController.

    Includes request_id computed alias so API/clients that expect request_id work.
    """

    model_config = ConfigDict(extra="ignore", use_enum_values=False)

    optimization_id: str = Field(default_factory=lambda: _new_id("opt"))
    plan_version: int = 1
    task_profile_id: str = ""
    organization_id: str = ""
    tenant_id: Optional[str] = None
    selected_model: Dict[str, Any] = Field(default_factory=dict)
    selected_agent: Optional[Dict[str, Any]] = None
    selected_strategies: List[Dict[str, Any]] = Field(default_factory=list)
    verification_plan: Dict[str, Any] = Field(default_factory=dict)
    estimated_quality: float = 0.0
    estimated_reliability: float = 0.0
    estimated_cost: float = 0.0
    estimated_latency_ms: float = 0.0
    authorized_budget: Optional[float] = None
    decision_reasons: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    policy_compliance: Dict[str, Any] = Field(default_factory=dict)
    approval_required: bool = False
    status: str = "draft"  # draft | ready | fallback | rejected
    fallback_mode: Union[FallbackMode, str] = FallbackMode.HEALTHY
    snapshot_id: Optional[str] = None
    created_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def _sync_tenant(self) -> "OptimizationPlanV2":
        if not self.tenant_id and self.organization_id:
            object.__setattr__(self, "tenant_id", self.organization_id)
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def request_id(self) -> str:
        """API compatibility: request_id mirrors optimization_id."""
        return self.optimization_id

    @computed_field  # type: ignore[prop-decorator]
    @property
    def plan_id(self) -> str:
        """API compatibility alias."""
        return self.optimization_id


# ---------------------------------------------------------------------------
# Performance profiles
# ---------------------------------------------------------------------------

class AgentPerformanceProfile(BaseModel):
    """Agent x model performance evidence (tenant-scoped)."""

    model_config = ConfigDict(extra="ignore")

    profile_id: str = Field(default_factory=lambda: _new_id("aprof"))
    organization_id: str = "global"
    agent_id: str
    agent_version: str = "1.0.0"
    model_id: str
    task_domain: str = "general"
    total_runs: int = 0
    success_rate: float = 0.0
    avg_quality: float = 0.0
    avg_latency_ms: float = 0.0
    avg_cost_usd: float = 0.0
    confidence_score: float = 0.5
    updated_at: datetime = Field(default_factory=_utc_now)


class StrategyPerformanceProfile(BaseModel):
    """Strategy amplification value profile (tenant-scoped)."""

    model_config = ConfigDict(extra="ignore")

    profile_id: str = Field(default_factory=lambda: _new_id("sprof"))
    organization_id: str = "global"
    strategy_id: str
    strategy_version: str = "1.0.0"
    task_domain: str = "general"
    baseline_quality: float = 0.0
    strategy_quality: float = 0.0
    quality_improvement: float = 0.0
    incremental_cost_usd: float = 0.0
    incremental_latency_ms: float = 0.0
    value_ratio: float = 0.0
    sample_count: int = 0
    confidence_score: float = 0.5
    updated_at: datetime = Field(default_factory=_utc_now)


class AgentStrategyProfile(BaseModel):
    """Combined agent strategy preference / routing profile."""

    model_config = ConfigDict(extra="ignore")

    profile_id: str = Field(default_factory=lambda: _new_id("asprof"))
    organization_id: str = "global"
    agent_id: str
    agent_version: str = "1.0.0"
    preferred_strategies: List[str] = Field(default_factory=list)
    preferred_models: List[str] = Field(default_factory=list)
    forbidden_strategies: List[str] = Field(default_factory=list)
    default_optimization_mode: str = "balanced"
    min_quality_score: float = 0.70
    max_cost_usd: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=_utc_now)


# ---------------------------------------------------------------------------
# Strategy optimization helpers
# ---------------------------------------------------------------------------

class StrategyOptimizationRequest(BaseModel):
    """Request to optimize strategy selection for a task context."""

    model_config = ConfigDict(extra="ignore")

    request_id: str = Field(default_factory=lambda: _new_id("sreq"))
    organization_id: str = "default-org"
    task_id: str = Field(default_factory=lambda: _new_id("task"))
    task_domain: str = "general"
    optimization_mode: str = "balanced"
    candidate_strategies: List[str] = Field(default_factory=list)
    max_cost: Optional[float] = None
    max_latency_ms: Optional[float] = None
    min_quality_score: float = 0.70
    context: Dict[str, Any] = Field(default_factory=dict)


class StrategyOptimizationResult(BaseModel):
    """Result of strategy optimization."""

    model_config = ConfigDict(extra="ignore")

    request_id: str = ""
    selected_strategies: List[str] = Field(default_factory=list)
    rejected_strategies: List[str] = Field(default_factory=list)
    estimated_quality: float = 0.0
    estimated_cost: float = 0.0
    estimated_latency_ms: float = 0.0
    value_ratios: Dict[str, float] = Field(default_factory=dict)
    decision_reasons: List[str] = Field(default_factory=list)
    status: str = "ready"


# ---------------------------------------------------------------------------
# Learning candidates (schema side)
# ---------------------------------------------------------------------------

class LearningCandidate(BaseModel):
    """Proposed learning / promotion candidate."""

    model_config = ConfigDict(extra="ignore", use_enum_values=False)

    candidate_id: str = Field(default_factory=lambda: _new_id("learn"))
    organization_id: str = "global"
    candidate_type: str = "strategy"
    description: str = ""
    proposed_change_json: Dict[str, Any] = Field(default_factory=dict)
    baseline_metrics_json: Dict[str, Any] = Field(default_factory=dict)
    expected_improvement_json: Dict[str, Any] = Field(default_factory=dict)
    evidence_references: List[Any] = Field(default_factory=list)
    status: LearningCandidateStatus = LearningCandidateStatus.PROPOSED
    validation_results_json: Dict[str, Any] = Field(default_factory=dict)
    experiment_id: Optional[str] = None
    promoted_at: Optional[datetime] = None
    rolled_back_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_utc_now)


# ---------------------------------------------------------------------------
# Fallback state view (schema side — not ORM)
# ---------------------------------------------------------------------------

class FallbackState(BaseModel):
    """Schema view of circuit-breaker state."""

    model_config = ConfigDict(extra="ignore", use_enum_values=False)

    state_id: str = "c11-global-fallback-state"
    mode: FallbackMode = FallbackMode.HEALTHY
    failure_count: int = 0
    last_failure_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    circuit_opened_at: Optional[datetime] = None
    reason: Optional[str] = None
    total_fallbacks: int = 0
    updated_at: datetime = Field(default_factory=_utc_now)


__all__ = [
    # Enums
    "PolicyEnforcementLevel",
    "LearningCandidateStatus",
    "FallbackMode",
    "DecisionType",
    "OptimizationMode",
    # Policy
    "PolicyViolation",
    "GovernanceViolation",
    "PolicyCheckResult",
    "PolicyEvaluationResult",
    "ComplianceCheck",
    "GovernanceRule",
    "OptimizationPolicy",
    "GovernancePolicy",
    # Request / plan / audit
    "OptimizationRequest",
    "OptimizationDecision",
    "OptimizationSnapshot",
    "OptimizationPlanV2",
    # Profiles
    "AgentPerformanceProfile",
    "StrategyPerformanceProfile",
    "AgentStrategyProfile",
    # Strategy optimization
    "StrategyOptimizationRequest",
    "StrategyOptimizationResult",
    # Learning / fallback
    "LearningCandidate",
    "FallbackState",
]
