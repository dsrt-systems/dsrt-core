"""
DSRT C10 Comparison Contracts — Paired Experiment & Comparison Engine
(C10 §4, §7, INV-35, INV-36, INV-37).

A ComparisonExperiment is a controlled comparison of two or more
executions. Each ComparisonRun pairs multiple ExecutionTraces that
differ only in explicitly declared variables; everything else MUST be
held constant (INV-35). Outcomes include INCONCLUSIVE and
INVALID_PROTOCOL — we never force a winner (INV-36).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field

from schemas.domain.base import DSRTImmutableSchema, DSRTSchema, TimestampedSchema


class ComparisonMode(str, Enum):
    """How executions are compared (C10 §4)."""
    A_VS_B = "A_VS_B"             # Two configs, one task
    N_WAY = "N_WAY"               # 3+ configs, one task
    HOLDOUT = "HOLDOUT"           # One config, two task sets
    ABLATION = "ABLATION"         # Same config minus one variable


class ComparisonStatus(str, Enum):
    PENDING = "PENDING"
    PROVISIONING = "PROVISIONING"
    RUNNING = "RUNNING"
    EVALUATING = "EVALUATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INVALID_PROTOCOL = "INVALID_PROTOCOL"


class ComparisonOutcome(str, Enum):
    """Final verdict of a comparison (INV-36).

    INCONCLUSIVE: evidence insufficient to decide
    INVALID_PROTOCOL: configs differed in uncontrolled variables
    """
    A_WINS = "A_WINS"
    B_WINS = "B_WINS"
    TIE = "TIE"
    INCONCLUSIVE = "INCONCLUSIVE"
    INVALID_PROTOCOL = "INVALID_PROTOCOL"
    MULTI_WINNER = "MULTI_WINNER"  # for N_WAY


class ComparisonDimension(str, Enum):
    """Dimensions a comparison can measure (C10 §7)."""
    QUALITY = "quality"
    COST = "cost"
    LATENCY = "latency"
    RELIABILITY = "reliability"
    EVIDENCE_QUALITY = "evidence_quality"
    SAFETY = "safety"


# =============================================================================
# ComparisonExperiment — the parent plan
# =============================================================================


class ComparisonExperiment(TimestampedSchema):
    """A controlled comparison plan (C10 §4).

    An experiment defines the SHAPE of the comparison: what varies,
    what is held constant, what dimensions matter. Runs instantiate it.
    """
    id: str
    organization_id: str
    user_id: str

    name: str
    description: str | None = None

    mode: ComparisonMode

    # The task(s) under comparison
    task_ids: list[str] = Field(default_factory=list)

    # Variables declared to differ between configs (INV-35)
    varied_dimensions: list[str] = Field(default_factory=list)

    # Variables that MUST be held constant across all configs
    controlled_dimensions: list[str] = Field(default_factory=list)

    # Dimensions being measured
    measurement_dimensions: list[ComparisonDimension] = Field(default_factory=list)

    # Statistical acceptance thresholds
    min_runs_per_config: int = 1
    quality_tie_threshold: float = 0.02    # <2% diff = TIE
    cost_savings_requires_quality: bool = True  # INV-37

    status: ComparisonStatus
    outcome: ComparisonOutcome | None = None
    outcome_rationale: str | None = None

    created_by: str
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ComparisonExperimentCreate(DSRTSchema):
    organization_id: str
    user_id: str
    name: str
    description: str | None = None
    mode: ComparisonMode
    task_ids: list[str]
    configuration_ids: list[str]
    varied_dimensions: list[str] = Field(default_factory=list)
    controlled_dimensions: list[str] = Field(default_factory=list)
    measurement_dimensions: list[ComparisonDimension] = Field(default_factory=list)
    min_runs_per_config: int = 1
    quality_tie_threshold: float = 0.02
    cost_savings_requires_quality: bool = True


# =============================================================================
# ComparisonRun — one instance (one task × N configs)
# =============================================================================


class ComparisonRun(TimestampedSchema):
    """One instantiation of a comparison experiment."""
    id: str
    comparison_experiment_id: str
    organization_id: str

    task_id: str

    # Participating configurations (one per leg)
    configuration_ids: list[str] = Field(default_factory=list)

    # Resulting execution traces (one per leg) — populated as runs complete
    execution_trace_ids: list[str] = Field(default_factory=list)

    status: ComparisonStatus
    outcome: ComparisonOutcome | None = None

    # Protocol validity check — did configs actually differ only in varied dims?
    protocol_valid: bool | None = None
    protocol_violations: list[str] = Field(default_factory=list)

    run_index: int = 0  # for min_runs_per_config repetitions

    started_at: datetime | None = None
    completed_at: datetime | None = None


# =============================================================================
# ComparisonResult — the measured deltas
# =============================================================================


class DimensionComparison(DSRTSchema):
    """Measured difference along one dimension."""
    dimension: ComparisonDimension
    leg_values: dict[str, float] = Field(default_factory=dict)  # config_id -> value
    winner_config_id: str | None = None
    delta_absolute: float | None = None
    delta_relative: float | None = None
    confidence: str = "LOW"  # LOW | MEDIUM | HIGH
    tied_within_threshold: bool = False


class ComparisonResult(DSRTImmutableSchema):
    """Immutable record of a completed comparison (C10 §7)."""
    id: str
    comparison_run_id: str
    comparison_experiment_id: str
    organization_id: str

    outcome: ComparisonOutcome
    outcome_rationale: str

    # Per-dimension measurements
    dimensions: list[DimensionComparison] = Field(default_factory=list)

    # Participating legs: config_id -> execution_trace_id
    leg_map: dict[str, str] = Field(default_factory=dict)

    # Protocol validation summary
    protocol_valid: bool
    protocol_violations: list[str] = Field(default_factory=list)

    # Cost-savings guard (INV-37)
    cost_savings_valid: bool = True
    cost_savings_rationale: str | None = None

    computed_at: datetime
    created_at: datetime