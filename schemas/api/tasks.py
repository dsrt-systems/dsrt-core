"""API DTOs for /tasks endpoints."""

from __future__ import annotations

from schemas.domain import Task, TaskCreate
from schemas.domain.base import DSRTSchema


class TaskListResponse(DSRTSchema):
    tasks: list[Task]
    total: int