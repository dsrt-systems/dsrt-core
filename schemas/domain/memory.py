"""
Memory Domain Schemas (C4 §4-11, §38-43).

Defines the complete memory data model: records, versions, sources,
links, conflicts, proposals, and retrieval results.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from schemas.domain.base import DSRTImmutableSchema, DSRTSchema, TimestampedSchema
from schemas.domain.enums import (
    MemoryImportance,
    MemoryLinkType,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    MemoryVerificationState,
)


# =============================================================================
# Memory Core
# =============================================================================


class MemorySource(DSRTSchema):
    """Provenance source for a memory (C4 §6)."""
    source_type: str = Field(..., description="e.g. 'web', 'tool_execution', 'agent', 'user'")
    source_id: str | None = None
    tool_execution_id: str | None = None
    execution_id: str | None = None
    agent_slug: str | None = None
    url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryCreate(DSRTSchema):
    """Agent's proposal to create a new memory (C4 §10)."""
    memory_type: MemoryType
    content: str = Field(..., min_length=1, max_length=100000)
    scope: MemoryScope = MemoryScope.PROJECT
    scope_id: str | None = None
    importance: MemoryImportance = MemoryImportance.NORMAL
    structured_data: dict[str, Any] | None = None
    source: MemorySource | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Memory(TimestampedSchema):
    """A persisted memory record (C4 §5, §39)."""
    id: str
    organization_id: str
    scope_type: MemoryScope
    scope_id: str | None = None
    memory_type: MemoryType
    content: str
    structured_data: dict[str, Any] | None = None
    status: MemoryStatus = MemoryStatus.ACTIVE
    importance: MemoryImportance = MemoryImportance.NORMAL
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    verification_state: MemoryVerificationState = MemoryVerificationState.UNVERIFIED
    source_type: str | None = None
    source_id: str | None = None
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    superseded_by: str | None = None
    created_by: str | None = None
    version: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryVersion(TimestampedSchema):
    """Immutable version snapshot of a memory (C4 §40)."""
    id: str
    memory_id: str
    version: int
    content: str
    structured_data: dict[str, Any] | None = None
    previous_version: int | None = None
    change_reason: str = ""
    source: MemorySource | None = None
    author: str | None = None


# =============================================================================
# Memory Relationships
# =============================================================================


class MemoryLink(DSRTSchema):
    """A directed relationship between two memories (C4 §41)."""
    id: str
    source_memory_id: str
    target_memory_id: str
    link_type: MemoryLinkType
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryConflict(DSRTSchema):
    """A detected contradiction between memories (C4 §20)."""
    id: str
    memory_a_id: str
    memory_b_id: str
    conflict_type: str = Field(default="CONTRADICTION")
    description: str = ""
    resolution: str | None = None
    resolved: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Memory Retrieval
# =============================================================================


class MemoryQuery(DSRTSchema):
    """A retrieval query against the memory store (C4 §12-17)."""
    query: str = Field(..., min_length=1, max_length=10000)
    scope: MemoryScope = MemoryScope.PROJECT
    scope_id: str | None = None
    memory_types: list[MemoryType] | None = None
    status_filter: list[MemoryStatus] | None = None
    importance_min: MemoryImportance | None = None
    valid_at: datetime | None = None
    limit: int = Field(default=10, ge=1, le=100)
    include_expired: bool = False
    include_superseded: bool = False
    metadata_filter: dict[str, Any] | None = None


class MemoryRetrievalResult(DSRTSchema):
    """A single memory returned from a retrieval query."""
    memory: Memory
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    retrieval_method: str = Field(default="unknown", description="vector|keyword|temporal|metadata|hybrid")
    provenance: dict[str, Any] = Field(default_factory=dict)


class MemoryRetrievalResponse(DSRTSchema):
    """Complete response from a memory retrieval query."""
    results: list[MemoryRetrievalResult] = Field(default_factory=list)
    total_candidates: int = 0
    query: str = ""
    scope: MemoryScope = MemoryScope.PROJECT
    retrieval_time_ms: int = 0


# =============================================================================
# Memory Operations
# =============================================================================


class MemoryUpdate(DSRTSchema):
    """Patch to update an existing memory (C4 §11)."""
    content: str | None = None
    structured_data: dict[str, Any] | None = None
    status: MemoryStatus | None = None
    importance: MemoryImportance | None = None
    confidence: float | None = None
    verification_state: MemoryVerificationState | None = None
    valid_until: datetime | None = None
    change_reason: str = ""
    metadata: dict[str, Any] | None = None


class MemoryLinkCreate(DSRTSchema):
    """Create a link between two memories."""
    source_memory_id: str
    target_memory_id: str
    link_type: MemoryLinkType
    confidence: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)