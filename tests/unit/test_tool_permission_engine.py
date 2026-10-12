"""Unit tests for ToolPermissionEngine (C3 §11-15, §52)."""

from __future__ import annotations

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
    OrganizationRole,
    SideEffectClass,
    ToolRiskLevel,
)
from schemas.domain.tool import (
    ToolBrowserPermission,
    ToolCredentialPermission,
    ToolFilesystemPermission,
    ToolIdentity,
    ToolLimits,
    ToolManifest,
    ToolNetworkPermission,
    ToolPermissionDeclaration,
    ToolRetryPolicy,
)

from core.tools.errors import ToolApprovalRequiredError, ToolPermissionDeniedError
from core.tools.permissions import (
    OrgToolPolicy,
    TaskToolPolicy,
    ToolPermissionEngine,
)


def _make_tool_manifest(
    slug: str = "web.search",
    risk: ToolRiskLevel = ToolRiskLevel.LOW,
    side_effect: SideEffectClass = SideEffectClass.READ,
    network: bool = False,
    fs_read: bool = False,
    fs_write: bool = False,
    browser: bool = False,
    external: bool = False,
) -> ToolManifest:
    return ToolManifest(
        identity=ToolIdentity(slug=slug, name="T", version="1.0.0", category="test"),
        risk_level=risk,
        side_effect=side_effect,
        permissions=ToolPermissionDeclaration(
            network=ToolNetworkPermission(required=network, outbound=network),
            filesystem=ToolFilesystemPermission(read=fs_read, write=fs_write),
            browser=ToolBrowserPermission(control=browser),
            external_actions=external,
        ),
    )


def _make_agent_manifest(
    network: bool = True,
    fs_access: str = "workspace",
    browser: bool = False,
    external: bool = False,
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
            filesystem=FilesystemPermission(access=fs_access),
            browser=BrowserPermission(access=browser),
            external_actions=ExternalActionsPermission(access=external),
        ),
    )


class TestToolPermissionEngine:
    def test_safe_tool_allowed(self):
        engine = ToolPermissionEngine()
        tool = _make_tool_manifest(network=True)
        agent = _make_agent_manifest(network=True)
        check = engine.build_check(tool_manifest=tool, agent_manifest=agent)
        decision = engine.evaluate(check)
        assert decision.allowed is True
        assert decision.requires_approval is False

    def test_denied_when_agent_lacks_permission(self):
        engine = ToolPermissionEngine()
        tool = _make_tool_manifest(browser=True)
        agent = _make_agent_manifest(browser=False)
        check = engine.build_check(tool_manifest=tool, agent_manifest=agent)
        decision = engine.evaluate(check)
        assert decision.allowed is False
        assert len(decision.denial_reasons) > 0

    def test_denied_by_org_blocked_list(self):
        engine = ToolPermissionEngine(
            org_policy=OrgToolPolicy(blocked_tools=["web.search"]),
        )
        tool = _make_tool_manifest(slug="web.search")
        agent = _make_agent_manifest()
        check = engine.build_check(tool_manifest=tool, agent_manifest=agent)
        decision = engine.evaluate(check)
        assert decision.allowed is False

    def test_approval_required_for_high_risk(self):
        engine = ToolPermissionEngine()
        tool = _make_tool_manifest(risk=ToolRiskLevel.HIGH)
        agent = _make_agent_manifest()
        check = engine.build_check(tool_manifest=tool, agent_manifest=agent)
        decision = engine.evaluate(check)
        assert decision.allowed is False
        assert decision.requires_approval is True
        assert decision.approval_requirement is not None

    def test_enforce_raises_on_denial(self):
        engine = ToolPermissionEngine(
            org_policy=OrgToolPolicy(blocked_tools=["web.search"]),
        )
        tool = _make_tool_manifest(slug="web.search")
        agent = _make_agent_manifest()
        check = engine.build_check(tool_manifest=tool, agent_manifest=agent)
        with pytest.raises(ToolPermissionDeniedError):
            engine.enforce(check)

    def test_enforce_raises_on_approval(self):
        engine = ToolPermissionEngine()
        tool = _make_tool_manifest(risk=ToolRiskLevel.CRITICAL)
        agent = _make_agent_manifest()
        check = engine.build_check(tool_manifest=tool, agent_manifest=agent)
        with pytest.raises(ToolApprovalRequiredError):
            engine.enforce(check)

    def test_task_tool_limit_exceeded(self):
        engine = ToolPermissionEngine(
            task_policy=TaskToolPolicy(max_tool_calls=5),
        )
        tool = _make_tool_manifest()
        agent = _make_agent_manifest()
        check = engine.build_check(
            tool_manifest=tool,
            agent_manifest=agent,
            current_tool_calls=5,
        )
        decision = engine.evaluate(check)
        assert decision.allowed is False