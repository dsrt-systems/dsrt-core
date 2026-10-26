# Path: core/execution/comparison/contracts.py
"""
Contracts for comparative execution results.

Rules:
- Do not force a single universal winner.
- Cost-efficiency claims require comparable quality.
- Multi-configuration experiments are first-class (not fixed pairs).
- Invalid / inconclusive outcomes remain visible and explicit.
"""

from __future__ import annotations

import datetime
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ComparisonOutcomeKind(str, Enum):
    """High-level interpretation of a comparison (not a forced ranking)."""

    CANDIDATE_BETTER_QUALITY_LOWER_COST = "candidate_better_quality_lower_cost"
    CANDIDATE_BETTER_QUALITY_HIGHER_COST = "candidate_better_quality_higher_cost"
    BASELINE_CHEAPER_COMPARABLE_QUALITY = "baseline_cheaper_comparable_quality"
    BASELINE_BETTER_QUALITY = "baseline_better_quality"
    ALL_FAILED = "all_failed"
    PARTIAL = "partial"
    INCONCLUSIVE = "inconclusive"
    INVALID = "invalid"
    MIXED = "mixed"


class ConfigurationRunEvidence(BaseModel):
    """Normalized evidence for one configuration inside an experiment."""

    configuration_id: str
    configuration_label: str
    protocol: str
    execution_id: Optional[str] = None
    run_status: str = "UNKNOWN"

    # Quality / evaluation
    overall_score: Optional[float] = None
    task_success: Optional[bool] = None
    correctness_score: Optional[float] = None
    completeness_score: Optional[float] = None
    reliability_score: Optional[float] = None
    evaluation_confidence: Optional[float] = None
    evaluation_method: Optional[str] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)
    findings: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)

    # Economics
    total_cost_usd: Optional[float] = None
    cost_availability: str = "UNAVAILABLE"  # ACTUAL | ESTIMATED | UNAVAILABLE
    model_cost_usd: Optional[float] = None
    tool_cost_usd: Optional[float] = None
    verification_cost_usd: Optional[float] = None
    recovery_cost_usd: Optional[float] = None

    # Performance / reliability
    latency_ms: Optional[int] = None
    succeeded: bool = False
    failed: bool = False
    cancelled: bool = False
    error_count: int = 0
    repair_count: int = 0

    # Identity / provenance
    model_fingerprint: Optional[str] = None
    evaluator_version: Optional[str] = None
    trace_id: Optional[str] = None
    artifact_ids: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DimensionComparison(BaseModel):
    """Comparison along one dimension (quality, cost, latency, ...)."""

    dimension: str
    values: Dict[str, Any] = Field(default_factory=dict)
    ranking: List[str] = Field(default_factory=list)  # configuration_ids best → worst
    best_configuration_id: Optional[str] = None
    delta: Dict[str, Any] = Field(default_factory=dict)
    comparable: bool = True
    notes: List[str] = Field(default_factory=list)


class ComparisonRequest(BaseModel):
    """Input to the comparison engine."""

    experiment_id: str
    workspace_id: str
    runs: List[ConfigurationRunEvidence]
    baseline_configuration_id: Optional[str] = None
    quality_comparable_threshold: float = 0.05
    """Max absolute overall_score gap to treat quality as comparable."""
    quality_success_threshold: float = 0.7
    """Minimum overall_score (when present) to treat a run as quality-successful."""
    require_quality_for_savings: bool = True
    evaluator_version: str = "c10.10.0"
    protocol_valid: bool = True
    protocol_invalid_reasons: List[str] = Field(default_factory=list)


class ComparisonResult(BaseModel):
    """Full comparison output — evidence-backed, multi-configuration."""

    comparison_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    experiment_id: str
    workspace_id: str
    configurations: List[str] = Field(default_factory=list)
    configuration_labels: Dict[str, str] = Field(default_factory=dict)

    quality_comparison: DimensionComparison = Field(
        default_factory=lambda: DimensionComparison(dimension="quality")
    )
    completion_comparison: DimensionComparison = Field(
        default_factory=lambda: DimensionComparison(dimension="completion")
    )
    correctness_comparison: DimensionComparison = Field(
        default_factory=lambda: DimensionComparison(dimension="correctness")
    )
    reliability_comparison: DimensionComparison = Field(
        default_factory=lambda: DimensionComparison(dimension="reliability")
    )
    cost_comparison: DimensionComparison = Field(
        default_factory=lambda: DimensionComparison(dimension="cost")
    )
    latency_comparison: DimensionComparison = Field(
        default_factory=lambda: DimensionComparison(dimension="latency")
    )
    verification_comparison: DimensionComparison = Field(
        default_factory=lambda: DimensionComparison(dimension="verification")
    )
    recovery_comparison: DimensionComparison = Field(
        default_factory=lambda: DimensionComparison(dimension="recovery")
    )

    # Soft recommendations — not forced winners
    successful_configuration_ids: List[str] = Field(default_factory=list)
    cost_efficient_configuration_id: Optional[str] = None
    highest_quality_configuration_id: Optional[str] = None
    lowest_latency_configuration_id: Optional[str] = None

    outcome_kind: ComparisonOutcomeKind = ComparisonOutcomeKind.INCONCLUSIVE
    outcome_summary: str = ""
    findings: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)

    # Economics (claimable only under quality guards)
    cost_savings_vs_baseline: Optional[float] = None
    cost_savings_claimable: bool = False
    baseline_configuration_id: Optional[str] = None

    evaluator_version: str = "c10.10.0"
    protocol_valid: bool = True
    created_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc)
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)