"""Execution schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from schemas.domain.base import DSRTSchema, TimestampedSchema
from schemas.domain.enums import ExecutionStatus, ErrorCode


class ResourceLimits(DSRTSchema):
    max_duration_seconds: int = Field(gt=0)
    max_model_calls: int = Field(gt=0)
    max_tool_calls: int = Field(gt=0)
    max_storage_mb: int = Field(gt=0)
    max_tokens: int | None = Field(default=None, gt=0)


class ExecutionError(DSRTSchema):
    code: ErrorCode
    message: str
    metadata: dict = Field(default_factory=dict)


class Execution(TimestampedSchema):
    id: str
    task_id: str
    organization_id: str

    core_version: str
    agent_version_id: str
    model_id: str | None
    contract_version: str

    attempt: int
    status: ExecutionStatus

    resource_limits: ResourceLimits

    queued_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None

    last_event_sequence: int
    configuration_hash: str

    result_summary: dict | None
    error: ExecutionError | None = None