"""
Pure Permission Intersection Logic (C3 §12).

Deterministic, side-effect-free functions that compute the intersection
of tool requirements, agent permissions, and policy layers.

The fundamental rule: the MOST RESTRICTIVE applicable layer always wins.

These functions are intentionally pure — they take resolved data as input
and return decisions. No database I/O, no async, no side effects.
This makes them fully unit-testable in isolation.
"""

from __future__ import annotations

from schemas.domain.enums import SideEffectClass, ToolRiskLevel

from core.tools.permissions.decision import (
    ToolDenialReason,
    ToolPermissionCheck,
)


# Risk level ordering for comparison (higher = more dangerous)
_RISK_ORDER: dict[ToolRiskLevel, int] = {
    ToolRiskLevel.LOW: 1,
    ToolRiskLevel.MEDIUM: 2,
    ToolRiskLevel.HIGH: 3,
    ToolRiskLevel.CRITICAL: 4,
}


def check_agent_network(
    check: ToolPermissionCheck,
) -> list[ToolDenialReason]:
    """Check if the agent's network permission satisfies the tool's requirement."""
    reasons: list[ToolDenialReason] = []
    if check.tool_requires_network and not check.agent_network_required:
        reasons.append(ToolDenialReason.AGENT_NETWORK_NOT_PERMITTED)
    return reasons


def check_agent_filesystem(
    check: ToolPermissionCheck,
) -> list[ToolDenialReason]:
    """Check if the agent's filesystem permission satisfies the tool's requirement."""
    reasons: list[ToolDenialReason] = []
    agent_access = check.agent_filesystem_access

    if check.tool_requires_filesystem_read and agent_access == "none":
        reasons.append(ToolDenialReason.AGENT_FILESYSTEM_NOT_PERMITTED)

    if check.tool_requires_filesystem_write and agent_access not in ("workspace", "full"):
        reasons.append(ToolDenialReason.FILESYSTEM_WRITE_DENIED)

    if check.tool_requires_filesystem_delete and agent_access != "full":
        reasons.append(ToolDenialReason.FILESYSTEM_DELETE_DENIED)

    return reasons


def check_agent_browser(
    check: ToolPermissionCheck,
) -> list[ToolDenialReason]:
    """Check if the agent's browser permission satisfies the tool's requirement."""
    reasons: list[ToolDenialReason] = []

    if check.tool_requires_browser_control and not check.agent_browser_access:
        reasons.append(ToolDenialReason.AGENT_BROWSER_NOT_PERMITTED)

    if check.tool_requires_browser_downloads and not check.agent_browser_access:
        reasons.append(ToolDenialReason.BROWSER_DOWNLOAD_DENIED)

    if check.tool_requires_browser_uploads and not check.agent_browser_access:
        reasons.append(ToolDenialReason.BROWSER_UPLOAD_DENIED)

    return reasons


def check_agent_external_actions(
    check: ToolPermissionCheck,
) -> list[ToolDenialReason]:
    """Check if the agent's external actions permission satisfies the tool's requirement."""
    reasons: list[ToolDenialReason] = []

    if check.tool_requires_external_actions and not check.agent_external_actions_access:
        reasons.append(ToolDenialReason.AGENT_EXTERNAL_ACTIONS_NOT_PERMITTED)

    return reasons


def check_agent_credentials(
    check: ToolPermissionCheck,
) -> list[ToolDenialReason]:
    """Check if the agent is permitted to use credentials."""
    reasons: list[ToolDenialReason] = []

    if check.tool_requires_credentials:
        # Agents cannot directly access credentials unless explicitly permitted
        # by both the agent manifest and the organization policy.
        # For C3.4, we default to denying direct credential access.
        reasons.append(ToolDenialReason.AGENT_CREDENTIAL_NOT_PERMITTED)

    return reasons


def check_tool_lists(
    check: ToolPermissionCheck,
) -> list[ToolDenialReason]:
    """Check tool against allowed/blocked lists at all policy layers (C3 §12)."""
    reasons: list[ToolDenialReason] = []
    slug = check.tool_slug

    # Organization policy
    if check.org_blocked_tools and slug in check.org_blocked_tools:
        reasons.append(ToolDenialReason.TOOL_IN_BLOCKED_LIST)
    if check.org_allowed_tools and slug not in check.org_allowed_tools:
        reasons.append(ToolDenialReason.TOOL_NOT_IN_ALLOWED_LIST)

    # Task policy (more restrictive, never looser)
    if check.task_blocked_tools and slug in check.task_blocked_tools:
        reasons.append(ToolDenialReason.TOOL_IN_BLOCKED_LIST)
    if check.task_allowed_tools and slug not in check.task_allowed_tools:
        reasons.append(ToolDenialReason.TOOL_NOT_IN_ALLOWED_LIST)

    # Environment policy
    if check.env_blocked_tools and slug in check.env_blocked_tools:
        reasons.append(ToolDenialReason.ENVIRONMENT_POLICY_DENIED)
    if check.env_allowed_tools and slug not in check.env_allowed_tools:
        reasons.append(ToolDenialReason.ENVIRONMENT_POLICY_DENIED)

    return reasons


def check_risk_level(
    check: ToolPermissionCheck,
) -> list[ToolDenialReason]:
    """Check if the tool's risk level exceeds the organization's threshold."""
    reasons: list[ToolDenialReason] = []

    if check.org_max_risk_level is not None:
        tool_risk = _RISK_ORDER.get(check.tool_risk_level, 0)
        max_risk = _RISK_ORDER.get(check.org_max_risk_level, 4)
        if tool_risk > max_risk:
            reasons.append(ToolDenialReason.RISK_LEVEL_EXCEEDS_THRESHOLD)

    return reasons


def check_side_effects(
    check: ToolPermissionCheck,
) -> list[ToolDenialReason]:
    """Check if the tool's side-effect class is blocked by policy."""
    reasons: list[ToolDenialReason] = []

    if check.org_blocked_side_effects:
        if check.tool_side_effect in check.org_blocked_side_effects:
            reasons.append(ToolDenialReason.SIDE_EFFECT_BLOCKED)

    return reasons


def check_task_resource_limits(
    check: ToolPermissionCheck,
) -> list[ToolDenialReason]:
    """Check if the task's tool call limit has been exceeded (C3 §37)."""
    reasons: list[ToolDenialReason] = []

    if (
        check.task_max_tool_calls is not None
        and check.task_current_tool_calls >= check.task_max_tool_calls
    ):
        reasons.append(ToolDenialReason.TASK_TOOL_LIMIT_EXCEEDED)

    return reasons


def compute_all_denials(
    check: ToolPermissionCheck,
) -> list[ToolDenialReason]:
    """Run all intersection checks and return the union of all denial reasons.

    This is the single entry point for the pure intersection logic.
    The order of checks does not matter — all are evaluated and the
    union of all denials is returned. This ensures complete audit trails.
    """
    all_reasons: list[ToolDenialReason] = []

    all_reasons.extend(check_agent_network(check))
    all_reasons.extend(check_agent_filesystem(check))
    all_reasons.extend(check_agent_browser(check))
    all_reasons.extend(check_agent_external_actions(check))
    all_reasons.extend(check_agent_credentials(check))
    all_reasons.extend(check_tool_lists(check))
    all_reasons.extend(check_risk_level(check))
    all_reasons.extend(check_side_effects(check))
    all_reasons.extend(check_task_resource_limits(check))

    # Deduplicate while preserving order
    seen: set[ToolDenialReason] = set()
    unique: list[ToolDenialReason] = []
    for r in all_reasons:
        if r not in seen:
            seen.add(r)
            unique.append(r)

    return unique