"""
Arena API Schemas (C8 §55).

Request/response schemas for the Arena REST API.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from schemas.domain.base import DSRTSchema
from schemas.domain.enums import ArenaRunStatus, BenchmarkType, RegressionStatus


class CreateBenchmarkRequest(DSRTSchema):
    """POST /api/v1/benchmarks"""
    id: str = Field(..., min_length=1)
    version: str = "1.0.0"
    name: str = ""
    description: str = ""
    benchmark_type: BenchmarkType = BenchmarkType.CAPABILITY
    task_suite_id: str | None = None
    world_slug: str | None = None
    metrics: list[str] = Field(default_factory=list)


class BenchmarkResponse(DSRTSchema):
    id: str
    version: str
    name: str
    benchmark_type: str
    task_suite_id: str | None
    metrics: list[str]


class CreateExperimentRequest(DSRTSchema):
    """POST /api/v1/experiments"""
    benchmark_id: str
    name: str = ""
    configurations: list[dict[str, Any]] = Field(default_factory=list)
    repetitions: int = 1


class ArenaRunResponse(DSRTSchema):
    """GET /api/v1/arena/runs/{id}"""
    id: str
    benchmark_id: str
    experiment_id: str
    agent_slug: str
    agent_version: str
    model_slug: str | None
    world_slug: str | None
    status: ArenaRunStatus
    configuration_hash: str
    started_at: str | None
    completed_at: str | None


class TrajectoryResponse(DSRTSchema):
    """GET /api/v1/arena/runs/{id}/trajectory"""
    arena_run_id: str
    event_count: int
    tool_call_count: int
    model_call_count: int
    duration_ms: int
    events: list[dict[str, Any]] = Field(default_factory=list)


class MetricResponse(DSRTSchema):
    """GET /api/v1/arena/runs/{id}/metrics"""
    arena_run_id: str
    metrics: list[dict[str, Any]] = Field(default_factory=list)
    dimensions: dict[str, float] = Field(default_factory=dict)


class RegressionResponse(DSRTSchema):
    """GET /api/v1/arena/regressions"""
    benchmark_id: str
    baseline_version: str
    candidate_version: str
    results: list[dict[str, Any]] = Field(default_factory=list)


class CapabilityProfileResponse(DSRTSchema):
    """GET /api/v1/arena/capabilities"""
    agent_slug: str
    agent_version: str
    profiles: dict[str, float] = Field(default_factory=dict)