"""Unit tests for Context Engine v2 (C4 §26-33)."""

from __future__ import annotations

import uuid
import pytest

from schemas.domain.context import ContextBuildRequest
from schemas.domain.enums import MemoryScope
from schemas.domain.provider import ModelContextConfig
from sdk.agent import SDKAgentContext

from core.context.engine import ContextEngine
from core.context.profiles import ContextProfileManager
from core.memory.embeddings.store import EmbeddingStore
from core.memory.retrieval.engine import HybridRetrievalEngine
from core.memory.retrieval.ranking import HybridRanker
from core.repositories import (
    AgentRepository,
    CapabilityRepository,
    ExecutionRepository,
    MemoryRepository,
    OrganizationRepository,
    TaskRepository,
    UserRepository,
)
from core.storage.database import db_manager


async def _seed_execution(session):
    """Seed a full org → user → agent → task → execution stack to satisfy FKs."""
    suffix = uuid.uuid4().hex[:8]

    org_repo = OrganizationRepository(session)
    user_repo = UserRepository(session)
    org = await org_repo.create(name=f"Org {suffix}", slug=f"org-{suffix}")
    user = await user_repo.create(
        email=f"user-{suffix}@example.com",
        display_name="User",
        password_hash="hash",
    )
    await org_repo.add_member(organization_id=org.id, user_id=user.id, role="owner")

    cap_repo = CapabilityRepository(session)
    agent_repo = AgentRepository(session)
    cap = await cap_repo.create(
        slug=f"cap_{suffix}", name="Cap", description="D", version="1.0.0",
    )
    agent = await agent_repo.create_agent(
        slug=f"agent_{suffix}", name="Agent", description="D",
        category="test", publisher="dsrt",
    )
    agent_ver = await agent_repo.create_agent_version(
        agent_id=agent.id, version="1.0.0", contract_version="1.0",
        manifest={"identity": {"id": agent.slug, "version": "1.0.0"}},
        package_reference="pkg", configuration={}, requirements={}, permissions={},
    )
    await agent_repo.link_capability(agent_ver.id, cap.id)

    task_repo = TaskRepository(session)
    exe_repo = ExecutionRepository(session)
    task = await task_repo.create(
        organization_id=org.id, user_id=user.id,
        agent_slug=agent.slug, objective="Analyze the universe.",
    )
    execution = await exe_repo.create(
        task_id=task.id, organization_id=org.id,
        core_version="1.0.0", agent_version_id=agent_ver.id,
        contract_version="1.0", configuration_hash="0" * 64,
    )

    return org, user, task, execution


class TestContextProfileManager:
    def test_research_profile(self):
        profile = ContextProfileManager.get_profile("research_intelligence")
        assert profile.semantic_memory_priority == 0.8
        assert profile.recent_events_priority == 0.4
        assert profile.max_memory_items == 30

    def test_software_profile(self):
        profile = ContextProfileManager.get_profile("software_engineering")
        assert profile.semantic_memory_priority == 0.4
        assert profile.artifacts_priority == 0.8

    def test_default_profile(self):
        profile = ContextProfileManager.get_profile("unknown_agent")
        assert profile.semantic_memory_priority == 0.5


@pytest.mark.asyncio
class TestContextEngine:
    async def test_build_context_with_retrieval(self):
        async with db_manager.session() as session:
            # 1. Seed database hierarchy to satisfy foreign key constraints
            org, user, task, execution = await _seed_execution(session)

            # 2. Setup ContextEngine dependencies
            mem_repo = MemoryRepository(session)
            emb_store = EmbeddingStore(session)
            retrieval_engine = HybridRetrievalEngine(mem_repo, emb_store, HybridRanker())
            engine = ContextEngine(session, retrieval_engine)

            request = ContextBuildRequest(
                execution_id=execution.id,
                task_id=task.id,
                organization_id=org.id,
                agent_slug="research_intelligence",
                agent_version="1.0.0",
                memory_scopes=[MemoryScope.PROJECT],
            )

            agent_context = SDKAgentContext(
                execution_id=execution.id,
                task_id=task.id,
                organization_id=org.id,
                user_id=user.id,
                agent_slug="research_intelligence",
                agent_version="1.0.0",
                objective=task.objective,
            )

            model_config = ModelContextConfig(
                max_input_tokens=100000,
                max_output_tokens=4000,
            )

            # 3. Execute
            compiled, result = await engine.build_context(
                request=request,
                agent_context=agent_context,
                model_config=model_config,
            )

            # 4. Assertions
            assert compiled is not None
            assert result is not None

            # Messages assembled
            assert len(compiled.messages) >= 1
            assert compiled.total_tokens > 0

            # Result record persisted
            assert result.execution_id == execution.id
            assert result.task_id == task.id
            assert result.retrieval_strategy == "hybrid"
            assert result.build_time_ms >= 0