"""Unit tests for Conflict Detection & Deduplication (C4 §19-21)."""

from __future__ import annotations

import uuid
import pytest

from schemas.domain.enums import MemoryScope, MemoryType
from schemas.domain.memory import MemoryCreate

from core.memory.conflicts.detector import ConflictDetector
from core.memory.embeddings.store import EmbeddingStore
from core.memory.store import MemoryStore
from core.repositories import MemoryRepository, OrganizationRepository
from core.storage.database import db_manager


class TestDeduplicationAndConflicts:
    @pytest.mark.asyncio
    async def test_exact_duplicate_is_deduplicated(self):
        async with db_manager.session() as session:
            org_repo = OrganizationRepository(session)
            suffix = uuid.uuid4().hex[:8]
            org = await org_repo.create(name=f"Org {suffix}", slug=f"org-dedup-{suffix}")

            mem_repo = MemoryRepository(session)
            emb_store = EmbeddingStore(session)
            store = MemoryStore(mem_repo, embedding_store=emb_store)

            proposal = MemoryCreate(
                memory_type=MemoryType.SEMANTIC,
                content="PostgreSQL is the chosen primary database.",
                scope=MemoryScope.PROJECT,
                scope_id="proj_1",
            )

            # Write first time
            m1 = await store.write(organization_id=org.id, proposal=proposal)

            # Write second time with exact same content
            m2 = await store.write(organization_id=org.id, proposal=proposal)

            # Must return the SAME memory ID (deduplicated)
            assert m1.id == m2.id

    @pytest.mark.asyncio
    async def test_contradiction_creates_conflict_record(self):
        async with db_manager.session() as session:
            org_repo = OrganizationRepository(session)
            suffix = uuid.uuid4().hex[:8]
            org = await org_repo.create(name=f"Org {suffix}", slug=f"org-conf-{suffix}")

            mem_repo = MemoryRepository(session)
            emb_store = EmbeddingStore(session)
            store = MemoryStore(mem_repo, embedding_store=emb_store)

            p1 = MemoryCreate(
                memory_type=MemoryType.SEMANTIC,
                content="Company X has 100 employees in 2025.",
                scope=MemoryScope.PROJECT,
                scope_id="proj_2",
            )
            m1 = await store.write(organization_id=org.id, proposal=p1)

            p2 = MemoryCreate(
                memory_type=MemoryType.SEMANTIC,
                content="Company X has 250 employees in 2025.",
                scope=MemoryScope.PROJECT,
                scope_id="proj_2",
            )
            m2 = await store.write(organization_id=org.id, proposal=p2)

            # Both memories exist (not deduplicated because contents differ)
            assert m1.id != m2.id

            # A conflict record must exist linking m1 and m2
            conflicts = await mem_repo.list_unresolved_conflicts(org.id)
            assert len(conflicts) >= 1
            
            # Check link
            links = await mem_repo.get_links(m2.id, direction="outgoing")
            assert any(l.link_type == "CONTRADICTS" for l in links)