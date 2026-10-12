"""Unit tests for Memory Consolidation & Retention Workers (C4 §22-25)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from schemas.domain.enums import MemoryScope, MemoryStatus, MemoryType
from schemas.domain.memory import MemoryCreate

from core.memory.consolidation.worker import MemoryConsolidator
from core.memory.retention.enforcer import RetentionEnforcer
from core.memory.store import MemoryStore
from core.repositories import MemoryRepository, OrganizationRepository
from core.storage.database import db_manager


class TestRetentionEnforcer:
    @pytest.mark.asyncio
    async def test_enforces_expiration(self):
        async with db_manager.session() as session:
            org_repo = OrganizationRepository(session)
            suffix = uuid.uuid4().hex[:8]
            org = await org_repo.create(name=f"Org {suffix}", slug=f"org-ret-{suffix}")

            repo = MemoryRepository(session)
            store = MemoryStore(repo)

            now = datetime.now(timezone.utc)
            past = now - timedelta(days=2)
            future = now + timedelta(days=2)

            # Write memory that is already expired
            m1 = await store.write(
                organization_id=org.id,
                proposal=MemoryCreate(
                    memory_type=MemoryType.WORKING,
                    content="Stale state.",
                    scope=MemoryScope.EXECUTION,
                    valid_until=past,
                ),
            )

            # Write memory that is valid
            m2 = await store.write(
                organization_id=org.id,
                proposal=MemoryCreate(
                    memory_type=MemoryType.WORKING,
                    content="Current state.",
                    scope=MemoryScope.EXECUTION,
                    valid_until=future,
                ),
            )

            # Run enforcer
            enforcer = RetentionEnforcer(repo)
            expired_count = await enforcer.enforce_expiration(org.id)

            assert expired_count >= 1

            m1_refreshed = await repo.get_by_id(m1.id)
            assert m1_refreshed.status == MemoryStatus.EXPIRED.value

            m2_refreshed = await repo.get_by_id(m2.id)
            assert m2_refreshed.status == MemoryStatus.ACTIVE.value


class TestMemoryConsolidator:
    @pytest.mark.asyncio
    async def test_consolidates_episodic_to_semantic(self):
        async with db_manager.session() as session:
            org_repo = OrganizationRepository(session)
            suffix = uuid.uuid4().hex[:8]
            org = await org_repo.create(name=f"Org {suffix}", slug=f"org-cons-{suffix}")

            repo = MemoryRepository(session)
            store = MemoryStore(repo)
            consolidator = MemoryConsolidator(repo, store)

            project_id = f"proj_{suffix}"

            # Seed episodic memories
            for i in range(3):
                await store.write(
                    organization_id=org.id,
                    proposal=MemoryCreate(
                        memory_type=MemoryType.EPISODIC,
                        content=f"Agent observed fact {i}.",
                        scope=MemoryScope.PROJECT,
                        scope_id=project_id,
                    ),
                )

            # Run consolidation
            run = await consolidator.run_consolidation(
                organization_id=org.id,
                scope_type=MemoryScope.PROJECT,
                scope_id=project_id,
                batch_size=10,
            )

            assert run.status == "COMPLETED"
            assert run.episodes_processed == 3
            assert run.memories_created == 1

            # Verify the semantic memory was created
            semantic_mems = await repo.list_by_scope(
                organization_id=org.id,
                scope_type=MemoryScope.PROJECT.value,
                scope_id=project_id,
                memory_type=MemoryType.SEMANTIC.value,
            )
            assert len(semantic_mems) == 1
            assert "Consolidated insights" in semantic_mems[0].content
            assert "fact 1" in semantic_mems[0].content