"""API DTOs for /executions endpoints."""

from __future__ import annotations

from schemas.domain import Artifact, Execution, ExecutionEvent, UsageRecord
from schemas.domain.base import DSRTSchema


class ExecutionResponse(DSRTSchema):
    execution: Execution


class ExecutionTelemetryResponse(DSRTSchema):
    """
    The canonical telemetry package for C8 Arena (C1 §39).
    Contains the full state of the execution, trajectory, artifacts, and usage.
    """
    execution: Execution
    configuration_hash: str
    events: list[ExecutionEvent]
    artifacts: list[Artifact]
    usage: list[UsageRecord]