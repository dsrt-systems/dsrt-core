"""Unit tests for ToolRouter (C3 §10)."""

from __future__ import annotations

import uuid

import pytest

from schemas.domain.agent import (
    AgentIdentity,
    AgentManifest,
    AgentPermissions,
    AgentRequirements,
    BrowserPermission,
    ExternalActionsPermission,
    FilesystemPermission,
    NetworkPermission,
)
from schemas.domain.enums import (
    SideEffectClass,
    ToolRiskLevel,
)
from schemas.domain.tool import (
    ToolCapabilityDeclaration,
    ToolIdentity,
    ToolLimits,
    ToolManifest,
    ToolNetworkPermission,
    ToolPermissionDeclaration,
    ToolRetryPolicy,
)

from core.repositories.tool_repository import ToolRepository
from core.storage.database import db_manager
from core.tools.errors import (
    ToolApprovalRequiredError,
    ToolNotFoundError,
    ToolPermissionDeniedError,
)
from core.tools.permissions.engine import ToolPermissionEngine
from core.tools.permissions.policies import OrgToolPolicy
from core.tools.registry.registry import ToolRegistry
from core.tools.router.decision import ToolRouteStatus
from core.tools.router.router import ToolRouter


def _tool_manifest(
    slug: str,
    *,
    risk: ToolRiskLevel = ToolRiskLevel.LOW,
    side_effect: SideEffectClass = SideEffectClass.READ,
    network: bool = True,
) -> ToolManifest:
    return ToolManifest(
        identity=ToolIdentity(
            slug=slug, name="T", version="1.0.0", category="web",
        ),
        description="Test tool.",
        capabilities=[ToolCapabilityDeclaration(slug=slug)],
        risk_level=risk,
        side_effect=side_effect,
        permissions=ToolPermissionDeclaration(
            network=ToolNetworkPermission(required=network, outbound=network),
        ),
        limits=ToolLimits(timeout_seconds=30),
        retry=ToolRetryPolicy(allowed=True, max_attempts=3, idempotent=True),
    )


def _agent_manifest(
    *, network: bool = True, browser: bool = False, external: bool = False,
) -> AgentManifest:
    return AgentManifest(
        identity=AgentIdentity(
            id="test_agent", name="Test", version="1.0.0",
            contract_version="1.0", publisher="dsrt", category="test",
        ),
        capabilities=["test"],
        requirements=AgentRequirements(minimum_core_version="1.0.0"),
        permissions=AgentPermissions(
            network=NetworkPermission(required=network),
            filesystem=FilesystemPermission(access="workspace"),
            browser=BrowserPermission(access=browser),
            external_actions=ExternalActionsPermission(access=external),
        ),
    )


@pytest.mark.asyncio
async def test_router_resolves_registered_tool() -> None:
    slug = f"web.router.{uuid.uuid4().hex[:8]}"
    manifest = _tool_manifest(slug)

    async with db_manager.session() as session:
        repo = ToolRepository(session)
        registry = ToolRegistry(repo)
        engine = ToolPermissionEngine()
        router = ToolRouter(registry=registry, permission_engine=engine)

        await registry.register_tool(
            manifest=manifest, implementation_class="impl.A",
        )

        route = await router.route(
            tool_slug=slug,
            agent_manifest=_agent_manifest(network=True),
        )

        assert route.tool_slug == slug
        assert route.tool_version == "1.0.0"
        assert route.routing_decision.status == ToolRouteStatus.RESOLVED
        assert route.routing_decision.selected_candidate is not None
        assert route.routing_decision.permission_decision is not None
        assert route.routing_decision.permission_decision.allowed is True
        assert route.routing_decision.decision_latency_ms >= 0


@pytest.mark.asyncio
async def test_router_raises_on_unknown_tool() -> None:
    slug = f"nonexistent.{uuid.uuid4().hex[:8]}"

    async with db_manager.session() as session:
        repo = ToolRepository(session)
        registry = ToolRegistry(repo)
        engine = ToolPermissionEngine()
        router = ToolRouter(registry=registry, permission_engine=engine)

        with pytest.raises(ToolNotFoundError) as exc_info:
            await router.route(
                tool_slug=slug,
                agent_manifest=_agent_manifest(),
            )

        assert "routing_decision" in exc_info.value.metadata
        decision = exc_info.value.metadata["routing_decision"]
        assert decision["status"] == ToolRouteStatus.NOT_FOUND.value


@pytest.mark.asyncio
async def test_router_denies_when_permissions_insufficient() -> None:
    slug = f"web.perm.{uuid.uuid4().hex[:8]}"
    manifest = _tool_manifest(slug, network=True)

    async with db_manager.session() as session:
        repo = ToolRepository(session)
        registry = ToolRegistry(repo)
        engine = ToolPermissionEngine()
        router = ToolRouter(registry=registry, permission_engine=engine)

        await registry.register_tool(
            manifest=manifest, implementation_class="impl.A",
        )

        # Agent does NOT have network permission
        with pytest.raises(ToolPermissionDeniedError) as exc_info:
            await router.route(
                tool_slug=slug,
                agent_manifest=_agent_manifest(network=False),
            )

        assert "routing_decision" in exc_info.value.metadata
        decision = exc_info.value.metadata["routing_decision"]
        assert decision["status"] == ToolRouteStatus.DENIED.value
        assert decision["permission_decision"] is not None


@pytest.mark.asyncio
async def test_router_raises_approval_required_for_high_risk() -> None:
    slug = f"web.highrisk.{uuid.uuid4().hex[:8]}"
    manifest = _tool_manifest(slug, risk=ToolRiskLevel.HIGH, network=True)

    async with db_manager.session() as session:
        repo = ToolRepository(session)
        registry = ToolRegistry(repo)
        engine = ToolPermissionEngine()
        router = ToolRouter(registry=registry, permission_engine=engine)

        await registry.register_tool(
            manifest=manifest, implementation_class="impl.A",
        )

        with pytest.raises(ToolApprovalRequiredError) as exc_info:
            await router.route(
                tool_slug=slug,
                agent_manifest=_agent_manifest(network=True),
            )

        assert "routing_decision" in exc_info.value.metadata
        decision = exc_info.value.metadata["routing_decision"]
        assert decision["status"] == ToolRouteStatus.APPROVAL_REQUIRED.value
        assert decision["selected_candidate"] is not None


@pytest.mark.asyncio
async def test_router_blocks_tool_via_org_policy() -> None:
    slug = f"web.blocked.{uuid.uuid4().hex[:8]}"
    manifest = _tool_manifest(slug, network=True)

    async with db_manager.session() as session:
        repo = ToolRepository(session)
        registry = ToolRegistry(repo)
        engine = ToolPermissionEngine(
            org_policy=OrgToolPolicy(blocked_tools=[slug]),
        )
        router = ToolRouter(registry=registry, permission_engine=engine)

        await registry.register_tool(
            manifest=manifest, implementation_class="impl.A",
        )

        with pytest.raises(ToolPermissionDeniedError):
            await router.route(
                tool_slug=slug,
                agent_manifest=_agent_manifest(network=True),
            )


@pytest.mark.asyncio
async def test_router_includes_full_audit_trail() -> None:
    slug = f"web.audit.{uuid.uuid4().hex[:8]}"
    manifest = _tool_manifest(slug, network=True)

    async with db_manager.session() as session:
        repo = ToolRepository(session)
        registry = ToolRegistry(repo)
        engine = ToolPermissionEngine()
        router = ToolRouter(registry=registry, permission_engine=engine)

        await registry.register_tool(
            manifest=manifest, implementation_class="impl.A",
        )

        route = await router.route(
            tool_slug=slug,
            agent_manifest=_agent_manifest(network=True),
            request_id="req_test_audit_001",
        )

        decision = route.routing_decision
        assert decision.request_id == "req_test_audit_001"
        assert decision.tool_slug == slug
        assert decision.selected_candidate is not None
        assert decision.selected_candidate.tool_slug == slug
        assert decision.selected_candidate.tool_version == "1.0.0"
        assert len(decision.candidates_considered) >= 1
        assert decision.decided_at is not None
        assert decision.decision_latency_ms >= 0