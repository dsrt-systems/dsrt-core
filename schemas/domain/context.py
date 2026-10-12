"""
Context Engine v2 Schemas (C4 §26-33, §46-48).

Extends the C2 Context Compiler with memory-aware context profiles,
build requests, and provenance-tracked build results.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from schemas.domain.base import DSRTSchema, TimestampedSchema
from schemas.domain.enums import MemoryScope, MemoryType


class ContextProfile(DSRTSchema):
    """Agent-specific context allocation profile (C4 §47)."""
    agent_slug: str
    task_priority: float = Field(default=0.8, ge=0.0, le=1.0)
    recent_events_priority: float = Field(default=0.5, ge=0.0, le=1.0)
    semantic_memory_priority: float = Field(default=0.7, ge=0.0, le=1.0)
    episodic_memory_priority: float = Field(default=0.3, ge=0.0, le=1.0)
    artifacts_priority: float = Field(default=0.6, ge=0.0, le=1.0)
    procedural_memory_priority: float = Field(default=0.4, ge=0.0, le=1.0)
    max_memory_items: int = Field(default=20, ge=1, le=100)
    max_evidence_items: int = Field(default=30, ge=1, le=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextBuildRequest(DSRTSchema):
    """Request to build a model-ready context (C4 §44)."""
    execution_id: str
    task_id: str
    organization_id: str
    agent_slug: str
    agent_version: str
    model_context_limit: int = Field(default=128000, ge=1000)
    output_reserve_tokens: int = Field(default=4000, ge=0)
    profile: ContextProfile | None = None
    memory_scopes: list[MemoryScope] = Field(default_factory=lambda: [MemoryScope.TASK, MemoryScope.PROJECT])
    memory_types: list[MemoryType] | None = None
    include_recent_events: bool = True
    include_artifacts: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextBuildResult(TimestampedSchema):
    """Result of a context build operation (C4 §53)."""
    id: str
    execution_id: str
    task_id: str
    context_hash: str
    total_tokens: int
    memory_items_included: int = 0
    evidence_items_included: int = 0
    artifact_items_included: int = 0
    event_items_included: int = 0
    memory_ids: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    retrieval_strategy: str = "hybrid"
    compression_applied: bool = False
    state_dropped: bool = False
    build_time_ms: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)