"""
Memory SDK Contract (C1 §23, C4 §11, §64).

Agents propose memories; Core decides scope, retention, verification,
storage, deduplication, and vector generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SDKMemoryRecord:
    """A memory record proposal or retrieval result."""

    memory_type: str = "semantic"  # "semantic" | "episodic" | "procedural" | "working" | "entity" | "document"
    content: str = ""
    scope: str = "project"  # "execution" | "task" | "project" | "user" | "agent" | "organization" | "world"
    scope_id: str | None = None
    importance: str = "normal"  # "trivial" | "normal" | "important" | "critical"
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str | None = None  # Populated after Core persists
    confidence: float | None = None
    relevance_score: float | None = None  # Populated on retrieval
    retrieval_method: str | None = None  # Populated on retrieval


class MemorySDK(Protocol):
    """Memory SDK — persistent intelligence state interface (C4 §64)."""

    async def retrieve(
        self, query: str, scope: str = "project", limit: int = 10,
    ) -> list[SDKMemoryRecord]:
        """Retrieve relevant memories using hybrid search."""
        ...

    async def write(
        self, memory: SDKMemoryRecord | dict[str, Any],
    ) -> str:
        """Propose a memory to Core for persistence. Returns memory_id."""
        ...

    async def get(
        self, memory_id: str,
    ) -> SDKMemoryRecord | None:
        """Fetch a specific memory record by ID."""
        ...

    async def update(
        self, memory_id: str, patch: dict[str, Any],
    ) -> SDKMemoryRecord:
        """Update an existing memory, creating a new version snapshot."""
        ...

    async def link(
        self, source_memory_id: str, target_memory_id: str, link_type: str,
    ) -> None:
        """Create a directed relationship between two memories."""
        ...