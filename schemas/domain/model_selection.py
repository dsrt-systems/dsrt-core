"""
Model Selection Schemas for C11.3 Adaptive Model Selector.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ModelSelectionMode(str, Enum):
    AUTOMATIC = "automatic"
    USER_PREFERRED = "user_preferred"
    FIXED = "fixed"


class ModelTier(str, Enum):
    FLAGSHIP = "flagship"
    MID_TIER = "mid_tier"
    SPECIALIZED = "specialized"
    FAST_ECONOMY = "fast_economy"


class SubstitutionReason(str, Enum):
    NONE = "none"
    BUDGET_EXCEEDED = "budget_exceeded"
    LATENCY_EXCEEDED = "latency_exceeded"
    CONTEXT_WINDOW_TOO_SMALL = "context_window_too_small"
    MISSING_REQUIRED_CAPABILITY = "missing_required_capability"
    MODEL_FORBIDDEN = "model_forbidden"
    USER_PREFERRED_INFEASIBLE = "user_preferred_infeasible"
    OPTIMIZATION_UPGRADE = "optimization_upgrade"
    OPTIMIZATION_DOWNGRADE = "optimization_downgrade"


# ---------------------------------------------------------------------------
# Candidate (defined first — referenced by Request)
# ---------------------------------------------------------------------------

class ModelCandidate(BaseModel):
    """Candidate model evaluated during model selection."""
    model_id: str
    provider: str = ""
    estimated_cost: float = 0.0
    estimated_latency_ms: float = 0.0
    historical_quality_score: float = 0.0
    historical_reliability_score: float = 0.0
    is_policy_compliant: bool = True
    rejection_reason: Optional[str] = None
    # C11.3 fields
    context_window_tokens: int = 128_000
    max_output_tokens: int = 8_192
    supports_vision: bool = False
    supports_function_calling: bool = True
    tier: ModelTier = ModelTier.MID_TIER
    typical_latency_ms: float = 1_000.0
    cost_per_1k_input_tokens_usd: float = 0.003
    cost_per_1k_output_tokens_usd: float = 0.006


# ---------------------------------------------------------------------------
# Request / Result / Decision
# ---------------------------------------------------------------------------

class ModelSelectionRequest(BaseModel):
    """Request model for adaptive model selection."""
    task_id: str = ""
    organization_id: str = ""
    task_type: Optional[str] = None
    complexity_score: Optional[float] = None
    model_preference: str = "automatic"
    max_cost_usd: Optional[float] = None
    max_latency_ms: Optional[float] = None
    min_quality_score: Optional[float] = None
    # C11.3 fields
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    available_candidates: List[ModelCandidate] = Field(default_factory=list)
    task_profile: Any = None
    selection_mode: ModelSelectionMode = ModelSelectionMode.AUTOMATIC
    preferred_model_id: Optional[str] = None
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0


class ModelSelectionResult(BaseModel):
    """Result of adaptive model selection (C11.3) — original shape."""
    selected_model_id: str
    selection_mode: str = "automatic"
    candidates_considered: List[ModelCandidate] = Field(default_factory=list)
    rejected_models: List[str] = Field(default_factory=list)
    decision_reasons: List[str] = Field(default_factory=list)
    confidence_score: float = 1.0
    policy_constrained: bool = False
    fallback_used: bool = False
    estimated_cost: float = 0.0
    estimated_latency_ms: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FeasibilityCheckResult(BaseModel):
    """Outcome of evaluating a single candidate against task constraints."""
    model_id: str
    is_feasible: bool = True
    violations: List[str] = Field(default_factory=list)
    estimated_cost_usd: float = 0.0
    estimated_latency_ms: float = 0.0
    expected_quality: float = 0.0
    expected_reliability: float = 0.0


class ModelSelectionDecision(BaseModel):
    """Deterministic decision returned by the Adaptive Model Selector."""
    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str = ""
    organization_id: str = ""
    selected_model_id: str
    selection_mode: ModelSelectionMode = ModelSelectionMode.AUTOMATIC
    was_substituted: bool = False
    substitution_reason: SubstitutionReason = SubstitutionReason.NONE
    original_preferred_model_id: Optional[str] = None
    utility_score: float = 0.0
    estimated_cost_usd: float = 0.0
    estimated_latency_ms: float = 0.0
    expected_quality: float = 0.0
    expected_reliability: float = 0.0
    feasibility_evaluations: List[FeasibilityCheckResult] = Field(default_factory=list)
    explanation: str = ""