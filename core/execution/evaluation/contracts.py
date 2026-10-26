"""
Evaluation contracts — shared schemas for the Evaluation Engine.

These contracts are independent of any specific C8 evaluator implementation.
Adapters translate C8 responses into these shapes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Categories (spec §7)
# ---------------------------------------------------------------------------

class EvaluationCategory(str, Enum):
    TASK_SUCCESS = "TASK_SUCCESS"
    CORRECTNESS = "CORRECTNESS"
    COMPLETENESS = "COMPLETENESS"
    CONSTRAINT_ADHERENCE = "CONSTRAINT_ADHERENCE"
    EVIDENCE_QUALITY = "EVIDENCE_QUALITY"
    TOOL_EXECUTION = "TOOL_EXECUTION"
    RELIABILITY = "RELIABILITY"
    ARTIFACT_QUALITY = "ARTIFACT_QUALITY"
    SAFETY_AND_POLICY = "SAFETY_AND_POLICY"


class ScoreKind(str, Enum):
    """
    How a metric should be interpreted.

    NUMERIC_BOUNDED  — reliable 0..1 (or min..max) score
    NUMERIC_UNBOUNDED — reliable number without fixed bounds (e.g. count)
    ORDINAL          — ordered categorical (e.g. poor/fair/good/excellent)
    BOOLEAN          — pass/fail
    QUALITATIVE      — text-only; NO numeric score may be manufactured
    """
    NUMERIC_BOUNDED = "NUMERIC_BOUNDED"
    NUMERIC_UNBOUNDED = "NUMERIC_UNBOUNDED"
    ORDINAL = "ORDINAL"
    BOOLEAN = "BOOLEAN"
    QUALITATIVE = "QUALITATIVE"


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Evaluator reference
# ---------------------------------------------------------------------------

class EvaluatorRef(BaseModel):
    """Identity of the evaluator that produced a result."""

    evaluator_id: str
    evaluator_version: str
    evaluator_name: str = ""
    method: str = ""  # DETERMINISTIC | EVIDENCE | RUBRIC | COMPOSITE
    source: str = "C10"  # C10 local | C8 registry | human


# ---------------------------------------------------------------------------
# Input package
# ---------------------------------------------------------------------------

class EvaluationInput(BaseModel):
    """
    Everything the engine needs to evaluate one execution.

    Artifacts and traces are referenced by ID — not inlined — to keep
    the evaluation request small and auditable.
    """

    evaluation_id: str = Field(default_factory=lambda: str(uuid4()))
    execution_id: str
    workspace_id: str
    task_id: str

    # What was produced
    output_text: str | None = None
    output_structured: dict[str, Any] | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    trace_id: str | None = None

    # What was asked
    task_prompt: str = ""
    expected_output: str | None = None
    expected_schema: dict[str, Any] | None = None
    constraints: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)

    # Execution evidence
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    verification_results: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    execution_status: str = "COMPLETED"

    # Optional C8 binding
    evaluation_suite_id: str | None = None
    benchmark_id: str | None = None

    # Protocol context
    protocol_type: str = ""  # DIRECT | AMPLIFIED | ...
    model_fingerprint_hash: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Findings & limitations
# ---------------------------------------------------------------------------

class EvaluationFinding(BaseModel):
    """A single concrete observation from evaluation."""

    finding_id: str = Field(default_factory=lambda: str(uuid4()))
    category: EvaluationCategory
    severity: str = "info"  # info | warning | error | critical
    summary: str
    detail: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationLimitation(BaseModel):
    """
    Explicit record of what the evaluation could NOT determine.

    Required by the critical rule: never hide the absence of a reliable
    scoring method behind a fabricated number.
    """

    limitation_id: str = Field(default_factory=lambda: str(uuid4()))
    category: EvaluationCategory | None = None
    reason: str
    impact: str = ""  # what decision should NOT be made based on this gap


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class MetricDefinition(BaseModel):
    """Describes a metric independent of any single measurement."""

    metric_id: str
    name: str
    category: EvaluationCategory
    score_kind: ScoreKind
    description: str = ""
    min_value: float | None = None
    max_value: float | None = None
    unit: str | None = None


class NormalizedMetric(BaseModel):
    """
    A single measured value after normalization.

    For QUALITATIVE metrics, ``value`` is None and ``qualitative_value``
    carries the assessment. Manufacturing a float for qualitative work
    is forbidden.
    """

    metric_id: str
    name: str
    category: EvaluationCategory
    score_kind: ScoreKind

    # Numeric path
    value: float | None = None
    min_value: float | None = None
    max_value: float | None = None
    unit: str | None = None

    # Non-numeric path
    qualitative_value: str | None = None
    ordinal_value: str | None = None
    boolean_value: bool | None = None

    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    method: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    notes: str = ""

    @property
    def is_numeric(self) -> bool:
        return self.score_kind in (
            ScoreKind.NUMERIC_BOUNDED,
            ScoreKind.NUMERIC_UNBOUNDED,
        ) and self.value is not None