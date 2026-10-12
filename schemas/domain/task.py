"""Task schemas."""

from __future__ import annotations

from pydantic import Field

from schemas.domain.base import DSRTSchema, TimestampedSchema
from schemas.domain.enums import TaskStatus


class TaskConstraints(DSRTSchema):
    max_duration_seconds: int | None = Field(default=None, gt=0)
    max_model_calls: int | None = Field(default=None, gt=0)
    max_tool_calls: int | None = Field(default=None, gt=0)
    max_storage_mb: int | None = Field(default=None, gt=0)


class TaskCreate(DSRTSchema):
    agent_slug: str = Field(min_length=1, max_length=200)
    model_identifier: str | None = None
    objective: str = Field(min_length=1)
    input_payload: dict = Field(default_factory=dict)
    constraints: TaskConstraints = Field(default_factory=TaskConstraints)


class Task(TimestampedSchema):
    id: str
    organization_id: str
    user_id: str
    agent_slug: str
    model_identifier: str | None
    objective: str
    input_payload: dict
    constraints: TaskConstraints
    status: TaskStatus