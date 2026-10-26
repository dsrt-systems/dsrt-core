"""
Arena & Evaluation Domain Schemas (C8 §4-8, §13-16, §24-31, §38-44, §49-54, §75).

Defines the complete Arena data model: benchmarks, tasks, experiments,
runs, trajectories, evaluators, metrics, performance profiles, and regressions.

Core principles:
  - Benchmark ≠ Experiment ≠ Run (C8 §5)
  - No single quality score (C8 §2)
  - Evidence-first evaluation (C8 §30)
  - Trajectory is more important than final answer (C8 §18)
  - Configuration fingerprint for reproducibility (C8 §43)
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field

from schemas.domain.base import DSRTImmutableSchema, DSRTSchema, TimestampedSchema
from schemas.domain.enums import (
    ArenaRunStatus,
    BenchmarkType,
    EvaluatorType,
    FailureCategory,
    MetricType,
    RegressionStatus,
    TaskVisibility,
)


# =============================================================================
# Benchmark (C8 §5-7)
# =============================================================================


class BenchmarkConstraints(DSRTSchema):
    """Resource constraints for a benchmark."""
    max_duration_seconds: int = Field(default=1800, ge=1)
    max_cost_usd: float = Field(default=10.0, ge=0)
    max_model_calls: int = Field(default=100, ge=1)
    max_tool_calls: int = Field(default=500, ge=1)


class Benchmark(DSRTSchema):
    """A benchmark defines WHAT capability is being measured (C8 §5-6)."""
    id: str = Field(..., min_length=1, max_length=200)
    version: str = "1.0.0"
    name: str = ""
    description: str = ""
    benchmark_type: BenchmarkType = BenchmarkType.CAPABILITY
    task_suite_id: str | None = None
    world_slug: str | None = None
    world_version: str | None = None
    metrics: list[str] = Field(default_factory=list)
    constraints: BenchmarkConstraints = Field(default_factory=BenchmarkConstraints)
    content_hash: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Task (C8 §8-12)
# =============================================================================


class TaskSuccessConditions(DSRTSchema):
    """Hidden evaluation state (C8 §9). Not exposed to the agent."""
    report_exists: bool = False
    minimum_sources: int = 0
    claims_verified: bool = False
    schema_valid: bool = False
    tests_passed: bool = False
    custom_conditions: dict[str, Any] = Field(default_factory=dict)


class TaskDefinition(DSRTSchema):
    """A standardized Arena task (C8 §8)."""
    id: str = Field(..., min_length=1, max_length=200)
    version: str = "1.0"
    suite_id: str = ""
    objective: str = Field(..., min_length=1)
    objective_type: str = "investigate"
    input_payload: dict[str, Any] = Field(default_factory=dict)
    starting_world_snapshot: str | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)
    success_conditions: TaskSuccessConditions = Field(
        default_factory=TaskSuccessConditions,
    )
    visibility: TaskVisibility = TaskVisibility.PUBLIC
    seed: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskInstance(DSRTSchema):
    """A concrete instantiation of a task (C8 §11-12).

    For dynamic tasks, the seed and configuration produce a unique instance.
    """
    id: str
    task_definition_id: str
    task_version: str
    seed: int | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    hidden_state: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


# =============================================================================
# Experiment (C8 §33-34)
# =============================================================================


class ExperimentConfiguration(DSRTImmutableSchema):
    """One cell in the experiment matrix (C8 §34)."""
    agent_slug: str
    agent_version: str
    model_slug: str | None = None
    model_version: str | None = None
    world_slug: str | None = None
    world_version: str | None = None
    task_definition_id: str
    task_version: str = "1.0"
    configuration: dict[str, Any] = Field(default_factory=dict)


class Experiment(DSRTSchema):
    """An experiment defines WHAT configurations are compared (C8 §5, §33)."""
    id: str
    benchmark_id: str
    benchmark_version: str
    name: str = ""
    description: str = ""
    configurations: list[ExperimentConfiguration] = Field(default_factory=list)
    repetitions: int = Field(default=1, ge=1)
    organization_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Arena Run (C8 §13-14)
# =============================================================================


class ArenaRun(TimestampedSchema):
    """One concrete execution of an experiment configuration (C8 §13)."""
    id: str
    benchmark_id: str
    benchmark_version: str
    experiment_id: str
    task_definition_id: str
    task_instance_id: str | None = None
    agent_slug: str
    agent_version: str
    model_slug: str | None = None
    model_version: str | None = None
    world_slug: str | None = None
    world_version: str | None = None
    world_instance_id: str | None = None
    execution_id: str | None = None
    configuration_hash: str = ""
    status: ArenaRunStatus = ArenaRunStatus.CREATED
    started_at: datetime | None = None
    completed_at: datetime | None = None
    seed: int | None = None
    repetition: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Trajectory (C8 §16-19)
# =============================================================================


class TrajectoryEvent(DSRTSchema):
    """A single event in an Arena trajectory (C8 §17, §19)."""
    event_id: str
    sequence: int
    timestamp: str
    event_type: str
    source: str
    agent_version: str | None = None
    model_version: str | None = None
    world_version: str | None = None
    node_id: str | None = None
    tool_slug: str | None = None
    target: str | None = None
    latency_ms: int | None = None
    tokens: int | None = None
    cost_usd: float | None = None
    error: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class Trajectory(TimestampedSchema):
    """Complete trajectory of an Arena run (C8 §16)."""
    id: str
    arena_run_id: str
    execution_id: str
    event_count: int = 0
    start_state_hash: str = ""
    final_state_hash: str = ""
    artifact_count: int = 0
    tool_call_count: int = 0
    model_call_count: int = 0
    duration_ms: int = 0
    events: list[TrajectoryEvent] = Field(default_factory=list)
    configuration_hash: str = ""


# =============================================================================
# Evaluator (C8 §24-28, §57-59)
# =============================================================================


class EvaluatorConfig(DSRTSchema):
    """Configuration for an evaluator (C8 §58)."""
    id: str
    version: str = "1.0"
    evaluator_type: EvaluatorType = EvaluatorType.DETERMINISTIC
    name: str = ""
    description: str = ""
    criteria: dict[str, Any] = Field(default_factory=dict)
    model_slug: str | None = None
    model_version: str | None = None
    temperature: float | None = None
    prompt_template: str | None = None


# =============================================================================
# Metric (C8 §24, §29-30)
# =============================================================================


class MetricResult(DSRTSchema):
    """Result of computing a single metric (C8 §29).

    Always points back to evidence (C8 §30).
    """
    metric_id: str
    metric_type: MetricType
    metric_version: str = "1.0"
    value_numeric: float | None = None
    value_boolean: bool | None = None
    value_text: str | None = None
    evaluator_type: EvaluatorType = EvaluatorType.DETERMINISTIC
    sample_count: int = 1
    confidence: float | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    explanation: str = ""


# =============================================================================
# Performance Profile (C8 §31-32)
# =============================================================================


class PerformanceProfile(TimestampedSchema):
    """Multi-dimensional performance result (C8 §31).

    Dimensions are independent — never collapsed to one score (C8 §2).
    """
    id: str
    arena_run_id: str
    task_success: bool = False
    correctness: float | None = None
    completeness: float | None = None
    evidence_quality: float | None = None
    reliability: float | None = None
    recovery: float | None = None
    tool_efficiency: float | None = None
    constraint_adherence: float | None = None
    safety: float | None = None
    latency_ms: int = 0
    estimated_cost_usd: float = 0.0
    model_cost_usd: float = 0.0
    tool_cost_usd: float = 0.0
    world_cost_usd: float = 0.0
    human_intervention_count: int = 0
    model_call_count: int = 0
    tool_call_count: int = 0
    failure_count: int = 0
    recovery_count: int = 0
    metrics: list[MetricResult] = Field(default_factory=list)
    dimensions: dict[str, float] = Field(default_factory=dict)


# =============================================================================
# Regression (C8 §38-42)
# =============================================================================


class RegressionResult(DSRTSchema):
    """Result of comparing two versions (C8 §39)."""
    id: str
    benchmark_id: str
    metric_type: MetricType
    baseline_version: str
    candidate_version: str
    baseline_value: float | None = None
    candidate_value: float | None = None
    delta: float | None = None
    status: RegressionStatus = RegressionStatus.INCONCLUSIVE
    sample_size: int = 0
    evidence_refs: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


# =============================================================================
# Arena Result (C8 §75)
# =============================================================================


class ArenaResult(DSRTSchema):
    """Canonical Arena result for a run (C8 §75)."""
    run_id: str
    outcome: str
    artifacts: list[str] = Field(default_factory=list)
    verification: list[str] = Field(default_factory=list)
    metrics: list[MetricResult] = Field(default_factory=list)
    trajectory_ref: str = ""
    resource_usage: dict[str, Any] = Field(default_factory=dict)
    failures: list[str] = Field(default_factory=list)
    configuration_hash: str = ""
    performance_profile_id: str | None = None