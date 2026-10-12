"""
MemorySDK Implementation (C4.10 — replaces C1 stub).

Bridge between the Agent's SDK interface (`sdk.memory.*`) and Core's
Memory Fabric (Store → Repositories → Embeddings → Hybrid Retrieval).

Agents never touch the underlying database, pgvector, or memory store —
they only see normalized SDKMemoryRecord objects.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import MemoryImportance, MemoryScope, MemoryType
from schemas.domain.memory import (
    Memory,
    MemoryCreate,
    MemoryQuery,
    MemorySource,
    MemoryUpdate,
)

from core.memory.embeddings.store import EmbeddingStore
from core.memory.retrieval.engine import HybridRetrievalEngine
from core.memory.store import MemoryStore
from core.observability.logging import get_logger
from core.repositories import MemoryRepository
from sdk.agent.interfaces.memory import SDKMemoryRecord


logger = get_logger("sdk.memory")


class MemorySDKImpl:
    """Concrete implementation of MemorySDK backed by the DSRT Memory Fabric."""

    def __init__(
        self,
        session: AsyncSession,
        execution_id: str,
        task_id: str,
        organization_id: str,
        agent_slug: str,
    ) -> None:
        self._session = session
        self._execution_id = execution_id
        self._task_id = task_id
        self._organization_id = organization_id
        self._agent_slug = agent_slug

        # Lazy-initialized services on first use
        self._repo: MemoryRepository | None = None
        self._store: MemoryStore | None = None
        self._retrieval_engine: HybridRetrievalEngine | None = None

    def _ensure_services(self) -> tuple[MemoryStore, HybridRetrievalEngine]:
        if self._store is None or self._retrieval_engine is None:
            self._repo = MemoryRepository(self._session)
            emb_store = EmbeddingStore(self._session)
            self._store = MemoryStore(self._repo, embedding_store=emb_store)
            self._retrieval_engine = HybridRetrievalEngine(self._repo, emb_store)
        return self._store, self._retrieval_engine

    async def write(self, memory: SDKMemoryRecord | dict[str, Any]) -> str:
        """Propose a memory to Core for persistence. Returns memory_id."""
        store, _ = self._ensure_services()

        # Handle both SDKMemoryRecord dataclass and raw dict inputs
        if isinstance(memory, dict):
            m_type = memory.get("type") or memory.get("memory_type", "semantic")
            content = memory.get("content", "")
            scope_val = memory.get("scope", "project")
            scope_id = memory.get("scope_id")
            importance_val = memory.get("importance", "normal")
            metadata = memory.get("metadata", {})
        else:
            m_type = memory.memory_type
            content = memory.content
            scope_val = memory.scope
            scope_id = memory.scope_id
            importance_val = memory.importance
            metadata = memory.metadata

        # Map enum strings safely
        try:
            mem_type_enum = MemoryType(m_type)
        except ValueError:
            mem_type_enum = MemoryType.SEMANTIC

        try:
            scope_enum = MemoryScope(scope_val)
        except ValueError:
            scope_enum = MemoryScope.PROJECT

        try:
            importance_enum = MemoryImportance(importance_val)
        except ValueError:
            importance_enum = MemoryImportance.NORMAL

        proposal = MemoryCreate(
            memory_type=mem_type_enum,
            content=content,
            scope=scope_enum,
            scope_id=scope_id,
            importance=importance_enum,
            source=MemorySource(
                source_type="agent",
                execution_id=self._execution_id,
                agent_slug=self._agent_slug,
            ),
            metadata=metadata,
        )

        persisted = await store.write(
            organization_id=self._organization_id,
            proposal=proposal,
            created_by=self._agent_slug,
            execution_id=self._execution_id,
            agent_slug=self._agent_slug,
        )

        logger.info(
            "sdk_memory_written",
            memory_id=persisted.id,
            agent_slug=self._agent_slug,
            scope=scope_enum.value,
        )

        return persisted.id

    async def retrieve(
        self, query: str, scope: str = "project", limit: int = 10,
    ) -> list[SDKMemoryRecord]:
        """Retrieve relevant memories using hybrid search."""
        _, retrieval_engine = self._ensure_services()

        try:
            scope_enum = MemoryScope(scope)
        except ValueError:
            scope_enum = MemoryScope.PROJECT

        mem_query = MemoryQuery(
            query=query,
            scope=scope_enum,
            limit=limit,
        )

        response = await retrieval_engine.search(
            organization_id=self._organization_id,
            query=mem_query,
        )

        records: list[SDKMemoryRecord] = []
        for result in response.results:
            mem = result.memory
            records.append(
                SDKMemoryRecord(
                    id=mem.id,
                    memory_type=mem.memory_type.value,
                    content=mem.content,
                    scope=mem.scope_type.value,
                    scope_id=mem.scope_id,
                    importance=mem.importance,
                    confidence=mem.confidence,
                    relevance_score=result.relevance_score,
                    retrieval_method=result.retrieval_method,
                    metadata=dict(mem.metadata or {}),
                )
            )

        logger.debug(
            "sdk_memory_retrieved",
            query=query,
            scope=scope,
            results_count=len(records),
        )

        return records

    async def get(self, memory_id: str) -> SDKMemoryRecord | None:
        """Fetch a specific memory record by ID."""
        store, _ = self._ensure_services()

        try:
            mem = await store.get(memory_id, self._organization_id)
        except Exception:
            return None

        return SDKMemoryRecord(
            id=mem.id,
            memory_type=mem.memory_type.value,
            content=mem.content,
            scope=mem.scope_type.value,
            scope_id=mem.scope_id,
            importance=mem.importance,
            confidence=mem.confidence,
            metadata=dict(mem.metadata or {}),
        )

    async def update(
        self, memory_id: str, patch: dict[str, Any],
    ) -> SDKMemoryRecord:
        """Update an existing memory, creating a new version snapshot."""
        store, _ = self._ensure_services()

        update_payload = MemoryUpdate(
            content=patch.get("content"),
            structured_data=patch.get("structured_data"),
            change_reason=patch.get("change_reason", "Agent update via SDK"),
            metadata=patch.get("metadata"),
        )

        updated = await store.update(
            memory_id=memory_id,
            organization_id=self._organization_id,
            patch=update_payload,
            author=self._agent_slug,
            execution_id=self._execution_id,
        )

        return SDKMemoryRecord(
            id=updated.id,
            memory_type=updated.memory_type.value,
            content=updated.content,
            scope=updated.scope_type.value,
            scope_id=updated.scope_id,
            importance=updated.importance,
            confidence=updated.confidence,
            metadata=dict(updated.metadata or {}),
        )

    async def link(
        self, source_memory_id: str, target_memory_id: str, link_type: str,
    ) -> None:
        """Create a directed relationship between two memories."""
        store, _ = self._ensure_services()

        await store.link(
            source_memory_id=source_memory_id,
            target_memory_id=target_memory_id,
            link_type=link_type,
            organization_id=self._organization_id,
        )