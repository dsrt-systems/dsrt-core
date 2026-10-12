"""
Integration tests for Model Session Manager & Model Switching (C2.8).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from core.models.sessions.manager import ModelSessionManager
from core.repositories import (
    AgentRepository,
    CapabilityRepository,
    ExecutionRepository,
    OrganizationRepository,
    ProviderRepository,
    SessionRepository,
    TaskRepository,
    UserRepository,
)
from core.storage.database import db_manager
from schemas.domain.enums import ProviderType
from schemas.domain.session import ModelCheckpointCreate


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class TestSessionManager:
    async def test_session_lifecycle_and_model_switching(self):
        suffix = uuid.uuid4().hex[:8]

        async with db_manager.session() as session:
            # 1. Seed Organization & User
            org_repo = OrganizationRepository(session)
            user_repo = UserRepository(session)
            org = await org_repo.create(name=f"Org {suffix}", slug=f"org-{suffix}")
            user = await user_repo.create(
                email=f"user-{suffix}@example.com",
                display_name="User",
                password_hash="hash",
            )
            await org_repo.add_member(organization_id=org.id, user_id=user.id, role="owner")

            # 2. Seed Capabilities & Agent
            cap_repo = CapabilityRepository(session)
            agent_repo = AgentRepository(session)
            cap = await cap_repo.create(
                slug=f"cap_{suffix}", name="Cap", description="D", version="1.0.0"
            )
            agent = await agent_repo.create_agent(
                slug=f"agent_{suffix}",
                name="Agent",
                description="D",
                category="test",
                publisher="dsrt",
            )
            agent_ver = await agent_repo.create_agent_version(
                agent_id=agent.id,
                version="1.0.0",
                contract_version="1.0",
                manifest={"identity": {"id": agent.slug, "version": "1.0.0"}},
                package_reference="pkg",
                configuration={},
                requirements={},
                permissions={},
            )
            await agent_repo.link_capability(agent_ver.id, cap.id)

            # 3. Seed Task & Execution
            task_repo = TaskRepository(session)
            exe_repo = ExecutionRepository(session)
            task = await task_repo.create(
                organization_id=org.id,
                user_id=user.id,
                agent_slug=agent.slug,
                objective="Session test",
            )
            execution = await exe_repo.create(
                task_id=task.id,
                organization_id=org.id,
                core_version="1.0.0",
                agent_version_id=agent_ver.id,
                contract_version="1.0",
                configuration_hash="0" * 64,
            )

            # 4. Seed Providers & Models
            prov_repo = ProviderRepository(session)
            prv_a = await prov_repo.create_provider(
                slug=f"openai_{suffix}", name="OpenAI", provider_type=ProviderType.CLOUD.value
            )
            mdl_a = await prov_repo.create_model(
                provider_id=prv_a.id,
                slug=f"gpt4_{suffix}",
                name="GPT-4",
                model_identifier="gpt-4",
                version="1.0",
                capabilities={},
            )

            prv_b = await prov_repo.create_provider(
                slug=f"google_{suffix}", name="Google", provider_type=ProviderType.CLOUD.value
            )
            mdl_b = await prov_repo.create_model(
                provider_id=prv_b.id,
                slug=f"gemini_{suffix}",
                name="Gemini",
                model_identifier="gemini-1.5",
                version="1.0",
                capabilities={},
            )

            # 5. Test Session Manager & Model Switching
            session_repo = SessionRepository(session)
            manager = ModelSessionManager(session_repo)

            # --- Step A: Start Session with Model A ---
            sess_1 = await manager.get_or_create_active_session(
                execution_id=execution.id,
                target_model_id=mdl_a.id,
                target_provider_id=prv_a.id,
            )
            assert sess_1.model_id == mdl_a.id
            assert sess_1.status == "active"

            # --- Step B: Create Checkpoint for Session 1 ---
            chk_1 = await manager.create_checkpoint(
                ModelCheckpointCreate(
                    session_id=sess_1.id,
                    request_id="req_1",
                    context_hash="hash_ctx_1",
                    canonical_state_hash="hash_state_1",
                    output_hash="hash_out_1",
                )
            )
            assert chk_1.context_hash == "hash_ctx_1"

            # --- Step C: Request SAME Model A (reuses existing session) ---
            sess_1_continued = await manager.get_or_create_active_session(
                execution_id=execution.id,
                target_model_id=mdl_a.id,
                target_provider_id=prv_a.id,
            )
            assert sess_1_continued.id == sess_1.id

            # --- Step D: SWITCH to Model B (mid-task) ---
            sess_2 = await manager.get_or_create_active_session(
                execution_id=execution.id,
                target_model_id=mdl_b.id,
                target_provider_id=prv_b.id,
            )
            assert sess_2.id != sess_1.id
            assert sess_2.model_id == mdl_b.id
            assert sess_2.status == "active"

            # --- Step E: Verify old session was transitioned to 'switched' ---
            old_status_query = await session.execute(
                text("SELECT status FROM dsrt.model_sessions WHERE id = :id"),
                {"id": sess_1.id},
            )
            assert old_status_query.scalar_one() == "switched"