"""
Domain Schemas for C11.10 Observability & Explainability.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from schemas.domain.governance import OptimizationDecision, PolicyViolation


class DecisionChainExplanation(BaseModel):
    """Complete human- and machine-readable explanation of an optimization decision chain."""

    request_id: str
    plan_id: str
    tenant_id: str
    decisions: List[OptimizationDecision] = Field(default_factory=list)
    model_selection_reasoning: str
    strategy_selection_reasoning: str
    verification_pruning_reasoning: str
    governance_policy_applied: Optional[str] = None
    policy_violations: List[PolicyViolation] = Field(default_factory=list)
    fallback_active: bool = False
    cost_breakdown_usd: Dict[str, float] = Field(default_factory=dict)
    latency_breakdown_ms: Dict[str, float] = Field(default_factory=dict)
    risk_assessment: Dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ExecutionActuals(BaseModel):
    """Actual outcome telemetry reported from execution environment (C9/C10)."""

    request_id: str
    tenant_id: str
    actual_cost_usd: float = Field(ge=0.0)
    actual_latency_ms: float = Field(ge=0.0)
    actual_quality_score: float = Field(ge=0.0, le=1.0)
    actual_tokens_used: Optional[int] = 0
    actual_verification_passed: bool = True
    completed_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ReconciliationReport(BaseModel):
    """Report comparing predicted vs actual metrics with error calculation."""

    id: str
    request_id: str
    plan_id: str
    tenant_id: str
    predicted_cost_usd: float
    actual_cost_usd: float
    cost_error_pct: float
    predicted_latency_ms: float
    actual_latency_ms: float
    latency_error_pct: float
    predicted_quality_score: float
    actual_quality_score: float
    quality_error_pct: float
    reconciled_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class SystemMetricsSummary(BaseModel):
    """System-wide summary metrics for optimization efficiency."""

    total_optimizations: int
    total_cost_saved_usd: float
    avg_latency_reduction_pct: float
    fallback_events_count: int
    policy_violations_count: int
    prediction_mae_cost: float
    prediction_mae_latency: float
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )