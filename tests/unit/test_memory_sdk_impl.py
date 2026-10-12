"""Unit tests for live MemorySDKImpl (C4.10)."""

from __future__ import annotations

import uuid
import pytest

from core.repositories import OrganizationRepository
from core.storage.database import db_manager
from sdk.agent.adapters.memory_adapter import MemorySDKImpl
from sdk.agent.interfaces.memory import SDKMemoryRecord


async def _seed_org(session) -> str:
    suffix = uuid.uuid4().hex[:8]
    repo = OrganizationRepository(session)
    org = await repo.create(name=f"Org {suffix}", slug=f"org-{suffix}")
    return org.id


@pytest.mark.asyncio
class TestMemorySDKImpl:
    async def test_write_and_get_via_sdk(self):
        async with db_manager.session() as session:
            org_id = await _seed_org(session)

            sdk_mem = MemorySDKImpl(
                session=session,
                execution_id="exe_sdk_1",
                task_id="tsk_sdk_1",
                organization_id=org_id,
                agent_slug="research_intelligence",
            )

            # Write memory via SDK Record
            rec = SDKMemoryRecord(
                memory_type="semantic",
                content="PostgreSQL pgvector enables vector similarity search.",
                scope="project",
                importance="important",
            )

            mem_id = await sdk_mem.write(rec)
            assert mem_id.startswith("mem_")

            # Get memory via SDK
            fetched = await sdk_mem.get(mem_id)
            assert fetched is not None
            assert fetched.id == mem_id
            assert fetched.content == rec.content
            assert fetched.memory_type == "semantic"

    async def test_write_via_dict_payload(self):
        async with db_manager.session() as session:
            org_id = await _seed_org(session)

            sdk_mem = MemorySDKImpl(
                session=session,
                execution_id="exe_sdk_2",
                task_id="tsk_sdk_2",
                organization_id=org_id,
                agent_slug="research_intelligence",
            )

            payload = {
                "type": "episodic",
                "content": "Executed web search for quantum computing.",
                "scope": "task",
            }

            mem_id = await sdk_mem.write(payload)
            assert mem_id.startswith("mem_")

            fetched = await sdk_mem.get(mem_id)
            assert fetched is not None
            assert fetched.memory_type == "episodic"

    async def test_retrieve_via_sdk(self):
        async with db_manager.session() as session:
            org_id = await _seed_org(session)

            sdk_mem = MemorySDKImpl(
                session=session,
                execution_id="exe_sdk_3",
                task_id="tsk_sdk_3",
                organization_id=org_id,
                agent_slug="research_intelligence",
            )

            # Write 2 memories
            await sdk_mem.write(
                SDKMemoryRecord(
                    memory_type="semantic",
                    content="Quantum error correction threshold is 99.9%.",
                    scope="project",
                )
            )
            await sdk_mem.write(
                SDKMemoryRecord(
                    memory_type="semantic",
                    content="Superconducting qubits operate at millikelvin temperatures.",
                    scope="project",
                )
            )

            # Retrieve
            results = await sdk_mem.retrieve(
                query="quantum error correction threshold",
                scope="project",
                limit=5,
            )

            assert len(results) >= 1
            assert any("threshold" in r.content for r in results)

    async def test_update_via_sdk(self):
        async with db_manager.session() as session:
            org_id = await _seed_org(session)

            sdk_mem = MemorySDKImpl(
                session=session,
                execution_id="exe_sdk_4",
                task_id="tsk_sdk_4",
                organization_id=org_id,
                agent_slug="research_intelligence",
            )

            mem_id = await sdk_mem.write(
                SDKMemoryRecord(
                    memory_type="semantic",
                    content="Initial hypothesis.",
                    scope="project",
                )
            )

            updated = await sdk_mem.update(
                mem_id,
                patch={
                    "content": "Refined hypothesis supported by evidence.",
                    "change_reason": "New findings",
                },
            )

            assert updated.content == "Refined hypothesis supported by evidence."

    async def test_link_via_sdk(self):
        async with db_manager.session() as session:
            org_id = await _seed_org(session)

            sdk_mem = MemorySDKImpl(
                session=session,
                execution_id="exe_sdk_5",
                task_id="tsk_sdk_5",
                organization_id=org_id,
                agent_slug="research_intelligence",
            )

            m1_id = await sdk_mem.write(
                SDKMemoryRecord(memory_type="semantic", content="Claim A", scope="project")
            )
            m2_id = await sdk_mem.write(
                SDKMemoryRecord(memory_type="semantic", content="Claim B", scope="project")
            )

            # Link m2 -> m1
            await sdk_mem.link(m2_id, m1_id, "SUPPORTS")