"""
Memory API Schemas (C4 §54).

Request/response schemas for the Memory REST API.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from schemas.domain.base import DSRTSchema
from schemas.domain.enums import MemoryScope, MemoryStatus, MemoryType
from schemas.domain.memory import MemoryCreate, MemoryRetrievalResponse, MemoryUpdate


class MemoryCreateRequest(MemoryCreate):
    """POST /api/v1/memories — create a new memory."""
    pass


class MemoryUpdateRequest(MemoryUpdate):
    """PATCH /api/v1/memories/{id} — update a memory."""
    pass


class MemoryRetrieveRequest(DSRTSchema):
    """POST /api/v1/memories/retrieve — retrieve memories."""
    query: str = Field(..., min_length=1)
    scope: MemoryScope = MemoryScope.PROJECT
    scope_id: str | None = None
    memory_types: list[MemoryType] | None = None
    limit: int = Field(default=10, ge=1, le=100)


class MemoryListResponse(DSRTSchema):
    """GET /api/v1/memories — list memories."""
    memories: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    scope: MemoryScope | None = None
    status: MemoryStatus | None = None