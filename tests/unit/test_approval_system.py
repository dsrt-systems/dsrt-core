"""Unit tests for the Approval System (C3 §15, §49)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from core.api.errors.exceptions import AuthorizationError, NotFoundError, ValidationError
from core.repositories.approval_repository import ApprovalRepository
from core.storage.database import db_manager
from core.tools.approvals.service import ApprovalService
from core.repositories import (
    AgentRepository,
    CapabilityRepository,
    ExecutionRepository,
    OrganizationRepository,
    TaskRepository,
    UserRepository,
)


def _unique_tex_id(label: str = "") -> str:
    """Generate a unique tool_execution_id for safe test isolation on live Supabase DB."""
    return f"tex_{label}_{uuid.uuid4().hex[:12]}"


async def _seed_execution(
    session,
    tool_execution_ids: list[str] | None = None,
) -> tuple[Any, Any, Any]:
    """Seed a full org → user → agent → task → execution → tool_executions stack."""
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
        agent_slug=agent.slug, objective="Approval test",
    )
    execution = await exe_repo.create(
        task_id=task.id, organization_id=org.id,
        core_version="1.0.0", agent_version_id=agent_ver.id,
        contract_version="1.0", configuration_hash="0" * 64,
    )

    if tool_execution_ids:
        from core.storage.models.tool_execution import ToolExecution
        for te_id in tool_execution_ids:
            tool_exe = ToolExecution(
                id=te_id,
                request_id=f"req_{te_id}",
                tool_slug="email.send",
                tool_version="1.0.0",
                execution_id=execution.id,
                task_id=task.id,
                organization_id=org.id,
                agent_slug=agent.slug,
                agent_version="1.0.0",
            )
            session.add(tool_exe)
        await session.flush()

    return org, user, execution


class TestApprovalService:
    @pytest.mark.asyncio
    async def test_create_and_grant_approval(self):
        tex_id = _unique_tex_id("grant")
        async with db_manager.session() as session:
            org, user, execution = await _seed_execution(session, [tex_id])

            repo = ApprovalRepository(session)
            service = ApprovalService(repo)

            request = await service.create_request(
                organization_id=org.id,
                execution_id=execution.id,
                tool_execution_id=tex_id,
                tool_slug="email.send",
                tool_version="1.0.0",
                requested_action="Send email to user@example.com",
                risk_level="high",
                side_effect="EXTERNAL_ACTION",
                required_role="member",
                reason="HIGH risk + external action",
                expires_in_seconds=300,
            )
            assert request.id is not None
            assert request.status == "REQUESTED"

            decision = await service.decide(
                approval_request_id=request.id,
                decision="GRANTED",
                decided_by_user_id=user.id,
                decided_by_role="owner",
                reason="Approved by owner.",
            )
            assert decision.decision == "GRANTED"

            refreshed = await service.get_request(request.id)
            assert refreshed.status == "GRANTED"

    @pytest.mark.asyncio
    async def test_reject_approval(self):
        tex_id = _unique_tex_id("reject")
        async with db_manager.session() as session:
            org, user, execution = await _seed_execution(session, [tex_id])

            repo = ApprovalRepository(session)
            service = ApprovalService(repo)

            request = await service.create_request(
                organization_id=org.id,
                execution_id=execution.id,
                tool_execution_id=tex_id,
                tool_slug="db.delete",
                tool_version="1.0.0",
                requested_action="DELETE FROM users WHERE active = false",
                risk_level="critical",
                side_effect="IRREVERSIBLE",
                required_role="admin",
            )

            decision = await service.decide(
                approval_request_id=request.id,
                decision="REJECTED",
                decided_by_user_id=user.id,
                decided_by_role="owner",
                reason="Too dangerous.",
            )
            assert decision.decision == "REJECTED"

            refreshed = await service.get_request(request.id)
            assert refreshed.status == "REJECTED"

    @pytest.mark.asyncio
    async def test_cannot_decide_twice(self):
        tex_id = _unique_tex_id("twice")
        async with db_manager.session() as session:
            org, user, execution = await _seed_execution(session, [tex_id])

            repo = ApprovalRepository(session)
            service = ApprovalService(repo)

            request = await service.create_request(
                organization_id=org.id,
                execution_id=execution.id,
                tool_execution_id=tex_id,
                tool_slug="email.send",
                tool_version="1.0.0",
                requested_action="Send email",
                risk_level="high",
                side_effect="EXTERNAL_ACTION",
            )

            await service.decide(
                approval_request_id=request.id,
                decision="GRANTED",
                decided_by_user_id=user.id,
                decided_by_role="owner",
            )

            with pytest.raises(ValidationError, match="already"):
                await service.decide(
                    approval_request_id=request.id,
                    decision="REJECTED",
                    decided_by_user_id=user.id,
                    decided_by_role="owner",
                )

    @pytest.mark.asyncio
    async def test_insufficient_role_rejected(self):
        tex_id = _unique_tex_id("role")
        async with db_manager.session() as session:
            org, user, execution = await _seed_execution(session, [tex_id])

            repo = ApprovalRepository(session)
            service = ApprovalService(repo)

            request = await service.create_request(
                organization_id=org.id,
                execution_id=execution.id,
                tool_execution_id=tex_id,
                tool_slug="db.delete",
                tool_version="1.0.0",
                requested_action="DROP TABLE",
                risk_level="critical",
                side_effect="IRREVERSIBLE",
                required_role="admin",
            )

            with pytest.raises(AuthorizationError, match="role"):
                await service.decide(
                    approval_request_id=request.id,
                    decision="GRANTED",
                    decided_by_user_id=user.id,
                    decided_by_role="viewer",
                )

    @pytest.mark.asyncio
    async def test_invalid_decision_value_rejected(self):
        tex_id = _unique_tex_id("invalid")
        async with db_manager.session() as session:
            org, user, execution = await _seed_execution(session, [tex_id])

            repo = ApprovalRepository(session)
            service = ApprovalService(repo)

            request = await service.create_request(
                organization_id=org.id,
                execution_id=execution.id,
                tool_execution_id=tex_id,
                tool_slug="email.send",
                tool_version="1.0.0",
                requested_action="Send",
                risk_level="high",
                side_effect="EXTERNAL_ACTION",
            )

            with pytest.raises(ValidationError, match="GRANTED"):
                await service.decide(
                    approval_request_id=request.id,
                    decision="MAYBE",
                    decided_by_user_id=user.id,
                    decided_by_role="owner",
                )

    @pytest.mark.asyncio
    async def test_nonexistent_request_raises(self):
        async with db_manager.session() as session:
            repo = ApprovalRepository(session)
            service = ApprovalService(repo)

            with pytest.raises(NotFoundError):
                await service.get_request("apr_nonexistent_xxx")

    @pytest.mark.asyncio
    async def test_is_approved_returns_true_after_grant(self):
        tex_id = _unique_tex_id("approved")
        async with db_manager.session() as session:
            org, user, execution = await _seed_execution(session, [tex_id])

            repo = ApprovalRepository(session)
            service = ApprovalService(repo)

            request = await service.create_request(
                organization_id=org.id,
                execution_id=execution.id,
                tool_execution_id=tex_id,
                tool_slug="email.send",
                tool_version="1.0.0",
                requested_action="Send",
                risk_level="high",
                side_effect="EXTERNAL_ACTION",
            )

            await service.decide(
                approval_request_id=request.id,
                decision="GRANTED",
                decided_by_user_id=user.id,
                decided_by_role="owner",
            )

            approved = await service.is_approved(
                tool_slug="email.send",
                tool_version="1.0.0",
                execution_id=execution.id,
            )
            assert approved is True

    @pytest.mark.asyncio
    async def test_is_approved_returns_false_when_none(self):
        async with db_manager.session() as session:
            repo = ApprovalRepository(session)
            service = ApprovalService(repo)

            approved = await service.is_approved(
                tool_slug="email.send",
                tool_version="1.0.0",
                execution_id="exe_nonexistent",
            )
            assert approved is False

    @pytest.mark.asyncio
    async def test_list_pending(self):
        tex_id = _unique_tex_id("pending")
        async with db_manager.session() as session:
            org, user, execution = await _seed_execution(session, [tex_id])

            repo = ApprovalRepository(session)
            service = ApprovalService(repo)

            await service.create_request(
                organization_id=org.id,
                execution_id=execution.id,
                tool_execution_id=tex_id,
                tool_slug="email.send",
                tool_version="1.0.0",
                requested_action="Send",
                risk_level="high",
                side_effect="EXTERNAL_ACTION",
            )

            pending = await service.list_pending(org.id)
            assert len(pending) >= 1
            assert all(r.status in ("REQUESTED", "PENDING") for r in pending)