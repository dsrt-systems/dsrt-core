"""
DSRT C10 Evaluation Contracts (C10 §9).

The C10 EvaluationEngine is an ADAPTER over C6 (verification) and C8
(arena evaluators). It does NOT re-implement either; it bridges them
into a uniform shape the ComparisonEngine can consume.

An EvaluationResult is multi-dimensional (never collapsed to a single
score) — this mirrors C6 §5 and reinforces INV-37.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field

from schemas.domain.base import DSRTImmutableSchema, DSRTSchema


class EvaluationBackend(str, Enum):
    """Which underlying evaluator produced this result."""
    C6_VERIFICATION = "C6_VERIFICATION"
    C8_ARENA = "C8_ARENA"
    HYBRID = "HYBRID"
    HEURISTIC = "HEURISTIC"


class EvaluationDimension(str, Enum):
    """Dimensions the C10 evaluator reports (aligned with C6 §5)."""
    CORRECTNESS = "correctness"
    COMPLETENESS = "completeness"
    EVIDENCE_QUALITY = "evidence_quality"
    INTEGRITY = "integrity"
    RELIABILITY = "reliability"
    SAFETY = "safety"
    LATENCY = "latency"
    COST = "cost"
    CONSTRAINT_ADHERENCE = "constraint_adherence"


class DimensionScore(DSRTSchema):
    """A single dimension measurement."""
    dimension: EvaluationDimension
    score: float  # 0.0 - 1.0
    confidence: str = "LOW"
    sample_size: int = 0
    backend: EvaluationBackend
    notes: str | None = None


class EvaluationRequest(DSRTSchema):
    """Request body for evaluating a completed execution trace."""
    execution_trace_id: str
    organization_id: str
    backends: list[EvaluationBackend] = Field(
        default_factory=lambda: [EvaluationBackend.C6_VERIFICATION]
    )
    verification_policy_id: str | None = None
    arena_benchmark_id: str | None = None
    dimensions: list[EvaluationDimension] = Field(default_factory=list)
    custom_criteria: dict[str, Any] = Field(default_factory=dict)


class EvaluationResult(DSRTImmutableSchema):
    """Immutable multi-dimensional evaluation record."""
    id: str
    execution_trace_id: str
    organization_id: str

    backends_used: list[EvaluationBackend]

    # Per-dimension measurements (never collapsed)
    dimensions: list[DimensionScore] = Field(default_factory=list)

    # Underlying evaluation references
    verification_run_id: str | None = None
    arena_run_id: str | None = None

    # Overall qualitative verdict (INV-36 permits INCONCLUSIVE)
    verdict: str  # "PASS" | "FAIL" | "PASS_WITH_WARNINGS" | "INCONCLUSIVE"
    verdict_rationale: str

    # Protocol validity (did the evaluator consider this a valid run?)
    evaluation_valid: bool = True
    invalidation_reasons: list[str] = Field(default_factory=list)

    evaluated_at: datetime
    created_at: datetime