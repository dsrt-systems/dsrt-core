"""API response schema for execution events/trajectory."""

from __future__ import annotations

from schemas.domain import ExecutionEvent
from schemas.domain.base import DSRTSchema


class EventListResponse(DSRTSchema):
    events: list[ExecutionEvent]
    total: int
    execution_id: str