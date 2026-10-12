"""Unit tests for pure permission intersection logic (C3 §12)."""

from __future__ import annotations

import pytest

from schemas.domain.enums import OrganizationRole, SideEffectClass, ToolRiskLevel

from core.tools.permissions.decision import ToolDenialReason, ToolPermissionCheck
from core.tools.permissions.intersection import (
    check_agent_browser,
    check_agent_external_actions,
    check_agent_filesystem,
    check_agent_network,
    check_risk_level,
    check_side_effects,
    check_task_resource_limits,
    check_tool_lists,
    compute_all_denials,
)


def _base_check(**overrides) -> ToolPermissionCheck:
    """Create a minimal ToolPermissionCheck with optional overrides."""
    defaults = dict(
        tool_slug="web.search",
        tool_version="1.0.0",
        tool_risk_level=ToolRiskLevel.LOW,
        tool_side_effect=SideEffectClass.READ,
    )
    defaults.update(overrides)
    return ToolPermissionCheck(**defaults)


class TestAgentNetworkIntersection:
    def test_allowed_when_agent_has_network(self):
        check = _base_check(tool_requires_network=True, agent_network_required=True)
        assert check_agent_network(check) == []

    def test_denied_when_agent_lacks_network(self):
        check = _base_check(tool_requires_network=True, agent_network_required=False)
        reasons = check_agent_network(check)
        assert ToolDenialReason.AGENT_NETWORK_NOT_PERMITTED in reasons

    def test_allowed_when_tool_does_not_require_network(self):
        check = _base_check(tool_requires_network=False, agent_network_required=False)
        assert check_agent_network(check) == []


class TestAgentFilesystemIntersection:
    def test_read_allowed_with_workspace(self):
        check = _base_check(tool_requires_filesystem_read=True, agent_filesystem_access="workspace")
        assert check_agent_filesystem(check) == []

    def test_read_denied_with_none(self):
        check = _base_check(tool_requires_filesystem_read=True, agent_filesystem_access="none")
        reasons = check_agent_filesystem(check)
        assert ToolDenialReason.AGENT_FILESYSTEM_NOT_PERMITTED in reasons

    def test_write_allowed_with_workspace(self):
        """Workspace access permits writes within the isolated workspace (C3 §24)."""
        check = _base_check(tool_requires_filesystem_write=True, agent_filesystem_access="workspace")
        assert check_agent_filesystem(check) == []

    def test_write_denied_with_none(self):
        check = _base_check(tool_requires_filesystem_write=True, agent_filesystem_access="none")
        reasons = check_agent_filesystem(check)
        assert ToolDenialReason.FILESYSTEM_WRITE_DENIED in reasons

    def test_write_allowed_with_full(self):
        check = _base_check(tool_requires_filesystem_write=True, agent_filesystem_access="full")
        assert check_agent_filesystem(check) == []

    def test_delete_denied_with_workspace(self):
        """Workspace access does NOT permit deletes — only full access does (C3 §24, §25)."""
        check = _base_check(tool_requires_filesystem_delete=True, agent_filesystem_access="workspace")
        reasons = check_agent_filesystem(check)
        assert ToolDenialReason.FILESYSTEM_DELETE_DENIED in reasons

    def test_delete_allowed_with_full(self):
        check = _base_check(tool_requires_filesystem_delete=True, agent_filesystem_access="full")
        assert check_agent_filesystem(check) == []


class TestAgentBrowserIntersection:
    def test_allowed_when_agent_has_browser(self):
        check = _base_check(tool_requires_browser_control=True, agent_browser_access=True)
        assert check_agent_browser(check) == []

    def test_denied_when_agent_lacks_browser(self):
        check = _base_check(tool_requires_browser_control=True, agent_browser_access=False)
        reasons = check_agent_browser(check)
        assert ToolDenialReason.AGENT_BROWSER_NOT_PERMITTED in reasons


class TestAgentExternalActionsIntersection:
    def test_denied_when_agent_lacks_external(self):
        check = _base_check(
            tool_requires_external_actions=True,
            agent_external_actions_access=False,
        )
        reasons = check_agent_external_actions(check)
        assert ToolDenialReason.AGENT_EXTERNAL_ACTIONS_NOT_PERMITTED in reasons


class TestToolListsIntersection:
    def test_blocked_by_org(self):
        check = _base_check(org_blocked_tools=["web.search"])
        reasons = check_tool_lists(check)
        assert ToolDenialReason.TOOL_IN_BLOCKED_LIST in reasons

    def test_not_in_org_allowed_list(self):
        check = _base_check(org_allowed_tools=["filesystem.read"])
        reasons = check_tool_lists(check)
        assert ToolDenialReason.TOOL_NOT_IN_ALLOWED_LIST in reasons

    def test_blocked_by_task(self):
        check = _base_check(task_blocked_tools=["web.search"])
        reasons = check_tool_lists(check)
        assert ToolDenialReason.TOOL_IN_BLOCKED_LIST in reasons

    def test_blocked_by_environment(self):
        check = _base_check(env_blocked_tools=["web.search"])
        reasons = check_tool_lists(check)
        assert ToolDenialReason.ENVIRONMENT_POLICY_DENIED in reasons

    def test_allowed_when_in_all_lists(self):
        check = _base_check(
            org_allowed_tools=["web.search"],
            task_allowed_tools=["web.search"],
        )
        assert check_tool_lists(check) == []


class TestRiskLevelIntersection:
    def test_within_threshold(self):
        check = _base_check(
            tool_risk_level=ToolRiskLevel.MEDIUM,
            org_max_risk_level=ToolRiskLevel.HIGH,
        )
        assert check_risk_level(check) == []

    def test_exceeds_threshold(self):
        check = _base_check(
            tool_risk_level=ToolRiskLevel.CRITICAL,
            org_max_risk_level=ToolRiskLevel.MEDIUM,
        )
        reasons = check_risk_level(check)
        assert ToolDenialReason.RISK_LEVEL_EXCEEDS_THRESHOLD in reasons


class TestSideEffectIntersection:
    def test_blocked_side_effect(self):
        check = _base_check(
            tool_side_effect=SideEffectClass.IRREVERSIBLE,
            org_blocked_side_effects=[SideEffectClass.IRREVERSIBLE],
        )
        reasons = check_side_effects(check)
        assert ToolDenialReason.SIDE_EFFECT_BLOCKED in reasons

    def test_allowed_side_effect(self):
        check = _base_check(
            tool_side_effect=SideEffectClass.READ,
            org_blocked_side_effects=[SideEffectClass.IRREVERSIBLE],
        )
        assert check_side_effects(check) == []


class TestTaskResourceLimits:
    def test_within_limit(self):
        check = _base_check(task_max_tool_calls=10, task_current_tool_calls=5)
        assert check_task_resource_limits(check) == []

    def test_exceeds_limit(self):
        check = _base_check(task_max_tool_calls=10, task_current_tool_calls=10)
        reasons = check_task_resource_limits(check)
        assert ToolDenialReason.TASK_TOOL_LIMIT_EXCEEDED in reasons


class TestComputeAllDenials:
    def test_no_denials_for_safe_tool(self):
        check = _base_check(
            tool_requires_network=True,
            agent_network_required=True,
        )
        assert compute_all_denials(check) == []

    def test_multiple_denials_accumulated(self):
        check = _base_check(
            tool_requires_network=True,
            agent_network_required=False,
            tool_requires_browser_control=True,
            agent_browser_access=False,
            org_blocked_tools=["web.search"],
        )
        reasons = compute_all_denials(check)
        assert len(reasons) >= 3
        assert ToolDenialReason.AGENT_NETWORK_NOT_PERMITTED in reasons
        assert ToolDenialReason.AGENT_BROWSER_NOT_PERMITTED in reasons
        assert ToolDenialReason.TOOL_IN_BLOCKED_LIST in reasons

    def test_deduplication(self):
        check = _base_check(
            org_blocked_tools=["web.search"],
            task_blocked_tools=["web.search"],
        )
        reasons = compute_all_denials(check)
        # Both produce TOOL_IN_BLOCKED_LIST but it should appear only once
        count = sum(1 for r in reasons if r == ToolDenialReason.TOOL_IN_BLOCKED_LIST)
        assert count == 1