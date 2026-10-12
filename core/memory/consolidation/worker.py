"""
Memory Consolidation Worker (C4 §22-23, §51).

Analyzes clusters of episodic/working memories to synthesize stable
semantic knowledge. Outputs proposals that are subject to standard
MemoryStore validation and deduplication rules.

For C4.9 v1, we implement a deterministic clustering strategy based
 on shared scope and metadata, synthesizing them into a semantic proposal.
"""

from __future__ import annotations

import uuid
from typing import Any

from schemas.domain.enums import MemoryImportance, MemoryScope, MemoryType
from schemas.domain.memory import MemoryCreate, MemorySource

from core.memory.store import MemoryStore
from core.observability.logging import get_logger
from core.repositories.memory_repository import MemoryRepository
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.memory_access import MemoryConsolidationRunORM


logger = get_logger("dsrt.memory.consolidation")


class MemoryConsolidator:
    """Synthesizes episodic memories into persistent semantic knowledge."""

    def __init__(
        self,
        repo: MemoryRepository,
        store: MemoryStore,
    ) -> None:
        self._repo = repo
        self._store = store

    async def run_consolidation(
        self,
        organization_id: str,
        scope_type: MemoryScope,
        scope_id: str | None = None,
        batch_size: int = 100,
    ) -> MemoryConsolidationRunORM:
        """Run a consolidation sweep over episodic memories in the given scope.

        Pipeline (C4 §51):
            1. Fetch recent EPISODIC memories
            2. Cluster by similarity/topic (simplified in v1 to scope grouping)
            3. Synthesize summary proposal
            4. Write proposal via MemoryStore
            5. Log consolidation run
        """
        run_id = new_id(IdPrefix.MEMORY)

        # 1. Fetch source memories
        episodes = await self._repo.list_by_scope(
            organization_id=organization_id,
            scope_type=scope_type.value,
            scope_id=scope_id,
            memory_type=MemoryType.EPISODIC.value,
            limit=batch_size,
        )

        if not episodes:
            return await self._record_run(
                organization_id, scope_type, scope_id, 0, 0, 0, 0, "COMPLETED"
            )

        # 2. Cluster / Synthesize (C4.9 v1: naive string concatenation for demonstration)
        # In a full deployment, this step delegates to a lightweight Model Fabric call
        # to generate a clean "Semantic Summary" of the 5-10 clustered episodes.
        synthesized_text = "Consolidated insights from recent episodes:\n"
        for ep in episodes:
            synthesized_text += f"- {ep.content}\n"

        if len(synthesized_text) > 4000:
            synthesized_text = synthesized_text[:4000] + "... [TRUNCATED]"

        # 3. Create Semantic Proposal
        proposal = MemoryCreate(
            memory_type=MemoryType.SEMANTIC,
            content=synthesized_text,
            scope=scope_type,
            scope_id=scope_id,
            importance=MemoryImportance.NORMAL,
            source=MemorySource(
                source_type="consolidation_worker",
                metadata={"source_episode_ids": [ep.id for ep in episodes]},
            ),
        )

        # 4. Write Proposal (MemoryStore handles deduplication and conflict detection)
        try:
            mem = await self._store.write(
                organization_id=organization_id,
                proposal=proposal,
                created_by="system.consolidator",
            )
            created = 1
        except Exception as e:
            logger.error(
                "consolidation_write_failed",
                run_id=run_id,
                error=str(e),
            )
            return await self._record_run(
                organization_id, scope_type, scope_id, len(episodes), 0, 0, 0, "FAILED"
            )

        # 5. Record Audit Log
        # Note: Conflicts are tracked internally by MemoryStore via the embeddings detector
        return await self._record_run(
            organization_id, scope_type, scope_id, len(episodes), created, 0, 0, "COMPLETED"
        )

    async def _record_run(
        self,
        org_id: str,
        scope_type: MemoryScope,
        scope_id: str | None,
        episodes: int,
        created: int,
        conflicts: int,
        superseded: int,
        status: str,
    ) -> MemoryConsolidationRunORM:
        run = MemoryConsolidationRunORM(
            organization_id=org_id,
            scope_type=scope_type.value,
            scope_id=scope_id,
            episodes_processed=episodes,
            memories_created=created,
            conflicts_detected=conflicts,
            memories_superseded=superseded,
            status=status,
        )
        self._repo.session.add(run)
        await self._repo.session.flush()
        return run