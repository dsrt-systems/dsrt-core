"""
Context Compiler Schemas (C2 §24-25).

Defines budgets, provenance tracking, and the resulting compiled context.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from schemas.domain.base import DSRTImmutableSchema, DSRTSchema
from schemas.domain.model_fabric import ModelMessage


class ContextBudget(DSRTSchema):
    """Token budget allocations for context compilation (C2 §24)."""

    system_reserve: int = Field(default=2000, ge=0)
    task_reserve: int = Field(default=4000, ge=0)
    working_state_reserve: int = Field(default=4000, ge=0)
    tools_reserve: int = Field(default=4000, ge=0)
    output_reserve: int = Field(default=4000, ge=0)

    # Remaining tokens after reserves are distributed among these dynamically
    evidence_max_tokens: int = Field(default=30000, ge=0)
    memory_max_tokens: int = Field(default=20000, ge=0)
    history_max_tokens: int = Field(default=20000, ge=0)


class ContextProvenanceItem(DSRTImmutableSchema):
    """Traces where a piece of compiled context came from (C2 §25)."""

    item_id: str
    source_type: str  # e.g., "memory", "tool_result", "artifact", "state"
    original_size_tokens: int
    included_size_tokens: int
    was_truncated: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class CompiledContext(DSRTImmutableSchema):
    """The final provider-ready context window."""

    messages: list[ModelMessage]
    system_context: dict[str, Any] | None = None
    
    total_tokens: int = 0
    output_budget_reserved: int = 0
    
    provenance: list[ContextProvenanceItem] = Field(default_factory=list)
    
    # Did we have to drop low-priority items (like memory) to fit the window?
    state_dropped: bool = False