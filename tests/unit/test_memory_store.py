"""Unit tests for Memory Store & Repository (C4 §10)."""

from __future__ import annotations

import uuid
import pytest

from schemas.domain.enums import MemoryImportance, MemoryScope, MemoryStatus, MemoryType
from schemas.domain.memory import MemoryCreate, MemorySource, MemoryUpdate

from core.api.errors.exceptions import NotFoundError, ValidationError
from core.memory.store import MemoryStore
from core.repositories import MemoryRepository, OrganizationRepository
from core.storage.database import db_manager


async def _seed_org(session) -> str:
    """Seed an organization and return its ID."""
    suffix = uuid.uuid4().hex[:8]
    repo = OrganizationRepository(session)
    org = await repo.create(name=f"Org {suffix}", slug=f"org-{suffix}")
    return org.id


class TestMemoryStore:
    @pytest.mark.asyncio
    async def test_write_and_get(self):
        async with db_manager.session() as session:
            org_id = await _seed_org(session)
            store = MemoryStore(MemoryRepository(session))

            proposal = MemoryCreate(
                memory_type=MemoryType.SEMANTIC,
                content="PostgreSQL is the primary database for DSRT Core.",
                scope=MemoryScope.PROJECT,
                scope_id="project_alpha",
                importance=MemoryImportance.IMPORTANT,
            )

            memory = await store.write(
                organization_id=org_id,
                proposal=proposal,
                agent_slug="research_intelligence",
            )

            assert memory.id.startswith("mem_")
            assert memory.content == proposal.content
            assert memory.memory_type == MemoryType.SEMANTIC
            assert memory.scope_type == MemoryScope.PROJECT
            assert memory.status == MemoryStatus.ACTIVE
            assert memory.version == 1

            # Retrieve
            fetched = await store.get(memory.id, org_id)
            assert fetched.id == memory.id
            assert fetched.content == memory.content

    @pytest.mark.asyncio
    async def test_write_with_source_provenance(self):
        async with db_manager.session() as session:
            org_id = await _seed_org(session)
            store = MemoryStore(MemoryRepository(session))

            proposal = MemoryCreate(
                memory_type=MemoryType.EPISODIC,
                content="Searched for quantum computing papers on 2025-10-04.",
                scope=MemoryScope.TASK,
                source=MemorySource(
                    source_type="web",
                    url="https://example.com/search",
                    agent_slug="research_intelligence",
                ),
            )

            memory = await store.write(
                organization_id=org_id,
                proposal=proposal,
                agent_slug="research_intelligence",
                execution_id="exe_test_123",
            )

            assert memory.id is not None
            assert memory.memory_type == MemoryType.EPISODIC

    @pytest.mark.asyncio
    async def test_update_creates_new_version(self):
        async with db_manager.session() as session:
            org_id = await _seed_org(session)
            repo = MemoryRepository(session)
            store = MemoryStore(repo)

            proposal = MemoryCreate(
                memory_type=MemoryType.SEMANTIC,
                content="Company X has 100 employees.",
                scope=MemoryScope.PROJECT,
            )
            memory = await store.write(organization_id=org_id, proposal=proposal)
            assert memory.version == 1

            patch = MemoryUpdate(
                content="Company X has 250 employees (updated Q4 2025).",
                change_reason="New data from annual report.",
            )
            updated = await store.update(
                memory.id, org_id, patch, author="analyst_agent",
            )

            assert updated.version == 2
            assert "250" in updated.content

            # Verify version history
            versions = await repo.list_versions(memory.id)
            assert len(versions) == 2
            assert versions[0].version == 1
            assert versions[1].version == 2
            assert versions[1].change_reason == "New data from annual report."

    @pytest.mark.asyncio
    async def test_archive_soft_deletes(self):
        async with db_manager.session() as session:
            org_id = await _seed_org(session)
            store = MemoryStore(MemoryRepository(session))

            proposal = MemoryCreate(
                memory_type=MemoryType.WORKING,
                content="Temporary plan step.",
                scope=MemoryScope.EXECUTION,
            )
            memory = await store.write(organization_id=org_id, proposal=proposal)
            assert memory.status == MemoryStatus.ACTIVE

            archived = await store.archive(memory.id, org_id)
            assert archived.status == MemoryStatus.ARCHIVED

    @pytest.mark.asyncio
    async def test_cross_org_get_denied(self):
        async with db_manager.session() as session:
            org_a = await _seed_org(session)
            org_b = await _seed_org(session)
            store = MemoryStore(MemoryRepository(session))

            proposal = MemoryCreate(
                memory_type=MemoryType.SEMANTIC,
                content="Secret org A data.",
                scope=MemoryScope.ORGANIZATION,
            )
            memory = await store.write(organization_id=org_a, proposal=proposal)

            # Org B cannot read Org A's memory
            with pytest.raises(NotFoundError):
                await store.get(memory.id, org_b)

    @pytest.mark.asyncio
    async def test_list_by_scope(self):
        async with db_manager.session() as session:
            org_id = await _seed_org(session)
            store = MemoryStore(MemoryRepository(session))

            project_id = f"proj_{uuid.uuid4().hex[:8]}"
            for i in range(3):
                await store.write(
                    organization_id=org_id,
                    proposal=MemoryCreate(
                        memory_type=MemoryType.SEMANTIC,
                        content=f"Fact {i} about the project.",
                        scope=MemoryScope.PROJECT,
                        scope_id=project_id,
                    ),
                )

            results = await store.list_by_scope(
                organization_id=org_id,
                scope_type="project",
                scope_id=project_id,
            )
            assert len(results) >= 3

    @pytest.mark.asyncio
    async def test_link_memories(self):
        async with db_manager.session() as session:
            org_id = await _seed_org(session)
            store = MemoryStore(MemoryRepository(session))

            m1 = await store.write(
                organization_id=org_id,
                proposal=MemoryCreate(
                    memory_type=MemoryType.SEMANTIC,
                    content="Claim A.",
                    scope=MemoryScope.PROJECT,
                ),
            )
            m2 = await store.write(
                organization_id=org_id,
                proposal=MemoryCreate(
                    memory_type=MemoryType.SEMANTIC,
                    content="Claim B supports Claim A.",
                    scope=MemoryScope.PROJECT,
                ),
            )

            await store.link(
                source_memory_id=m2.id,
                target_memory_id=m1.id,
                link_type="SUPPORTS",
                organization_id=org_id,
            )

            # Verify link exists
            repo = MemoryRepository(session)
            links = await repo.get_links(m2.id, direction="outgoing")
            assert len(links) == 1
            assert links[0].link_type == "SUPPORTS"
            assert links[0].target_memory_id == m1.id

    @pytest.mark.asyncio
    async def test_empty_content_rejected(self):
        """Whitespace-only content is rejected by Pydantic's str_strip_whitespace + min_length."""
        from pydantic import ValidationError as PydanticValidationError

        with pytest.raises(PydanticValidationError, match="string_too_short"):
            MemoryCreate(
                memory_type=MemoryType.SEMANTIC,
                content="   ",
                scope=MemoryScope.PROJECT,
            )

    @pytest.mark.asyncio
    async def test_keyword_search(self):
        async with db_manager.session() as session:
            org_id = await _seed_org(session)
            repo = MemoryRepository(session)
            store = MemoryStore(repo)

            unique_term = f"xyzzy_{uuid.uuid4().hex[:8]}"
            await store.write(
                organization_id=org_id,
                proposal=MemoryCreate(
                    memory_type=MemoryType.SEMANTIC,
                    content=f"The {unique_term} protocol was adopted in Q3.",
                    scope=MemoryScope.PROJECT,
                ),
            )

            results = await repo.search_content(
                organization_id=org_id,
                query=unique_term,
            )
            assert len(results) >= 1
            assert unique_term in results[0].content