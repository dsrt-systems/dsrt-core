"""
Domain schemas for C11.7 Verification Optimizer.

Defines schemas for verification tiers, strategies, step configurations,
pipeline plans, cascade rules, and verification requests/decisions.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class VerificationTier(str, Enum):
    """Tiers of verification tools and testing protocols."""
    SYNTAX_LINT = "syntax_lint"
    UNIT_TEST = "unit_test"
    STATIC_ANALYSIS = "static_analysis"
    INTEGRATION_TEST = "integration_test"
    SECURITY_SCAN = "security_scan"
    PROPERTY_TEST = "property_test"
    CONSENSUS_VERIFICATION = "consensus_verification"


class VerificationStrategyType(str, Enum):
    """Presets for verification intensity and coverage."""
    MINIMAL = "minimal"
    BALANCED = "balanced"
    THOROUGH = "thorough"
    EXHAUSTIVE = "exhaustive"
    ADAPTIVE = "adaptive"


class VerificationStep(BaseModel):
    """Individual verification step within a pipeline cascade."""

    step_id: str = Field(default_factory=lambda: f"vstep-{uuid4().hex[:8]}")
    tier: VerificationTier = Field(..., description="Verification tier for this step")
    tool_name: str = Field(..., description="Name of the execution tool/runner")
    estimated_cost: float = Field(..., ge=0.0, description="Estimated USD cost to execute step")
    estimated_latency_sec: float = Field(..., ge=0.0, description="Estimated execution time in seconds")
    failure_detection_prob: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Probability of catching an introduced defect"
    )
    required_pass_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Required score/ratio to pass (1.0 = 100% pass)"
    )
    is_blocking: bool = Field(
        default=True,
        description="Whether failure at this step immediately halts downstream execution"
    )
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Tool-specific operational flags or config parameters"
    )


class VerificationPipelineConfig(BaseModel):
    """Complete specification of a multi-tier verification pipeline."""

    pipeline_id: str = Field(default_factory=lambda: f"vpipe-{uuid4().hex[:8]}")
    strategy_type: VerificationStrategyType = Field(..., description="Strategy classification")
    steps: List[VerificationStep] = Field(..., description="Ordered cascade of verification steps")
    total_estimated_cost: float = Field(default=0.0, ge=0.0, description="Sum of step costs")
    total_estimated_latency_sec: float = Field(default=0.0, ge=0.0, description="Total expected latency")
    early_exit_on_failure: bool = Field(default=True, description="Stop cascade on first blocking failure")


class VerificationOptimizationRequest(BaseModel):
    """Request payload for constructing an optimized verification pipeline."""

    task_id: str = Field(..., description="Associated task identifier")
    organization_id: str = Field(default="default-org", description="Tenant/Org identifier")
    complexity_score: float = Field(default=0.5, ge=0.0, le=1.0, description="Task complexity level")
    risk_level: float = Field(default=0.5, ge=0.0, le=1.0, description="Assessed risk level (0=safe, 1=critical)")
    max_allowed_cost: Optional[float] = Field(default=None, ge=0.0, description="Cost limit for verification")
    max_allowed_latency_sec: Optional[float] = Field(default=None, ge=0.0, description="Latency budget limit")
    target_confidence: float = Field(default=0.85, ge=0.0, le=1.0, description="Target post-verification confidence")


class VerificationOptimizationPlan(BaseModel):
    """Optimized plan output containing selected cascade steps and economic trade-offs."""

    plan_id: str = Field(default_factory=lambda: f"vplan-{uuid4().hex[:8]}")
    task_id: str = Field(..., description="Task identifier")
    selected_strategy: VerificationStrategyType = Field(..., description="Selected strategy preset")
    pipeline: VerificationPipelineConfig = Field(..., description="Configured verification pipeline")
    tier_allocation: List[VerificationTier] = Field(..., description="List of active verification tiers")
    expected_confidence: float = Field(..., ge=0.0, le=1.0, description="Calculated confidence post-verification")
    estimated_cost: float = Field(..., ge=0.0, description="Total pipeline cost in USD")
    estimated_latency_sec: float = Field(..., ge=0.0, description="Total pipeline latency in seconds")
    cost_savings_ratio: float = Field(
        default=0.0,
        ge=0.0,
        description="Relative cost savings compared to exhaustive baseline verification"
    )
    created_at: datetime = Field(default_factory=_utc_now)
