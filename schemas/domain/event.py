"""ExecutionEvent schema — the canonical trajectory record."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from schemas.domain.base import DSRTSchema
from schemas.domain.enums import EventType


class ExecutionEventCreate(DSRTSchema):
    event_type: EventType | str
    source: str = Field(min_length=1, max_length=100)
    payload: dict = Field(default_factory=dict)
    request_id: str | None = None


class ExecutionEvent(DSRTSchema):
    id: str
    execution_id: str
    sequence: int
    event_type: str
    source: str
    payload: dict
    request_id: str | None
    timestamp: datetime