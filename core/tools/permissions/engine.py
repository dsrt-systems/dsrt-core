"""
Tool Permission Engine (C3 §11-15, §48-49, §52).

The central authorization service for all tool executions in DSRT.
Evaluates the complete permission intersection chain and produces
an auditable ToolPermissionDecision.

Architecture:
    Agent Request
        ↓
    ToolPermissionEngine.evaluate(check)
        ↓
    intersection.compute_all_denials(check)
        ↓
    approval_evaluator.evaluate_approval_requirement(...)
        ↓
    ToolPermissionDecision (ALLOWED | DENIED | APPROVAL_REQUIRED)

The engine is intentionally synchronous and pure at its core.
Database resolution of policies happens in the async wrapper.
"""

from __future__ import annotations

from typing import Any

from schemas.domain.agent import AgentManifest, AgentPermissions, AgentRequirements
from schemas.domain.enums import OrganizationRole, SideEffectClass, ToolRiskLevel
from schemas.domain.task import TaskConstraints
from schemas.domain.tool import ToolManifest

from core.api.errors.exceptions import AuthorizationError
from core.observability.logging import get_logger
from core.security.context import SecurityContext
from core.tools.errors import ToolApprovalRequiredError, ToolPermissionDeniedError
from core.tools.permissions.approval_evaluator import evaluate_approval_requirement
from core.tools.permissions.decision import (
    ToolApprovalRequirement,
    ToolDenialReason,
    ToolPermissionCheck,
    ToolPermissionDecision,
)
from core.tools.permissions.intersection import compute_all_denials
from core.tools.permissions.policies import (
    EnvironmentToolPolicy,
    OrgToolPolicy,
    TaskToolPolicy,
)


logger = get_logger("dsrt.tools.permissions")


class ToolPermissionEngine:
    """Authoritative tool permission evaluator for DSRT Core."""

    def __init__(
        self,
        org_policy: OrgToolPolicy | None = None,
        task_policy: TaskToolPolicy | None = None,
        env_policy: EnvironmentToolPolicy | None = None,
    ) -> None:
        self._org_policy = org_policy or OrgToolPolicy()
        self._task_policy = task_policy or TaskToolPolicy()
        self._env_policy = env_policy or EnvironmentToolPolicy()

    def _resolve_task_max_tool_calls(
        self, task_constraints: TaskConstraints | None,
    ) -> int | None:
        """Resolve the effective max_tool_calls by combining TaskConstraints and TaskToolPolicy.

        The MOST RESTRICTIVE limit wins (lowest non-None value).
        """
        candidates: list[int] = []

        if task_constraints and task_constraints.max_tool_calls is not None:
            candidates.append(task_constraints.max_tool_calls)

        if self._task_policy.max_tool_calls is not None:
            candidates.append(self._task_policy.max_tool_calls)

        if not candidates:
            return None

        return min(candidates)

    def build_check(
        self,
        *,
        tool_manifest: ToolManifest,
        agent_manifest: AgentManifest,
        security_context: SecurityContext | None = None,
        task_constraints: TaskConstraints | None = None,
        current_tool_calls: int = 0,
    ) -> ToolPermissionCheck:
        """Construct a ToolPermissionCheck from domain objects.

        This is the primary entry point for callers who have domain objects
        rather than raw check data.
        """
        tool_perms = tool_manifest.permissions
        agent_perms = agent_manifest.permissions
        agent_reqs = agent_manifest.requirements

        # Resolve user role
        user_role: OrganizationRole | None = None
        if security_context and security_context.active_organization_id:
            user_role = security_context.active_role()

        return ToolPermissionCheck(
            tool_slug=tool_manifest.identity.slug,
            tool_version=tool_manifest.identity.version,
            tool_risk_level=tool_manifest.risk_level,
            tool_side_effect=tool_manifest.side_effect,

            # Tool requirements
            tool_requires_network=tool_perms.network.required,
            tool_requires_network_outbound=tool_perms.network.outbound,
            tool_requires_filesystem_read=tool_perms.filesystem.read,
            tool_requires_filesystem_write=tool_perms.filesystem.write,
            tool_requires_filesystem_delete=tool_perms.filesystem.delete,
            tool_requires_browser_control=tool_perms.browser.control,
            tool_requires_browser_downloads=tool_perms.browser.downloads,
            tool_requires_browser_uploads=tool_perms.browser.uploads,
            tool_requires_credentials=tool_perms.credentials.access,
            tool_requires_external_actions=tool_perms.external_actions,
            tool_allowed_domains=tool_perms.network.allowed_domains,
            tool_blocked_domains=tool_perms.network.blocked_domains,

            # Agent permissions
            agent_network_required=agent_perms.network.required,
            agent_filesystem_access=agent_perms.filesystem.access,
            agent_browser_access=agent_perms.browser.access,
            agent_external_actions_access=agent_perms.external_actions.access,
            agent_required_tools=agent_reqs.required_tools,
            agent_optional_tools=agent_reqs.optional_tools,

            # Org policy
            org_allowed_tools=self._org_policy.allowed_tools,
            org_blocked_tools=self._org_policy.blocked_tools,
            org_max_risk_level=self._org_policy.max_risk_level,
            org_blocked_side_effects=self._org_policy.blocked_side_effects,

            # Task policy
            task_allowed_tools=self._task_policy.allowed_tools,
            task_blocked_tools=self._task_policy.blocked_tools,
            task_max_tool_calls=self._resolve_task_max_tool_calls(task_constraints),
            task_current_tool_calls=current_tool_calls,

            # Environment policy
            env_allowed_tools=self._env_policy.allowed_tools,
            env_blocked_tools=self._env_policy.blocked_tools,
            env_network_mode=self._env_policy.network_mode,

            # User context
            user_role=user_role,
        )

    def evaluate(self, check: ToolPermissionCheck) -> ToolPermissionDecision:
        """Evaluate a tool permission check and return an auditable decision.

        This is the core evaluation method. It is synchronous and pure —
        no database I/O, no async. All policy data must be pre-resolved
        in the ToolPermissionCheck.
        """
        # 1. Compute all denial reasons from intersection logic
        denial_reasons = compute_all_denials(check)

        # 2. If any hard denials exist, the tool is DENIED
        if denial_reasons:
            decision = ToolPermissionDecision(
                tool_slug=check.tool_slug,
                tool_version=check.tool_version,
                allowed=False,
                requires_approval=False,
                denial_reasons=denial_reasons,
                metadata={
                    "evaluation_stage": "intersection",
                    "denial_count": len(denial_reasons),
                },
            )
            logger.warning(
                "tool_permission_denied",
                tool_slug=check.tool_slug,
                reasons=[r.value for r in denial_reasons],
            )
            return decision

        # 3. Evaluate approval requirements
        approval_req = evaluate_approval_requirement(
            risk_level=check.tool_risk_level,
            side_effect=check.tool_side_effect,
            org_max_risk_without_approval=self._org_policy.max_risk_without_approval,
            org_side_effects_requiring_approval=self._org_policy.side_effects_requiring_approval,
            org_requires_approval_for_external=self._org_policy.requires_approval_for_external,
            user_role=check.user_role,
        )

        if approval_req is not None:
            decision = ToolPermissionDecision(
                tool_slug=check.tool_slug,
                tool_version=check.tool_version,
                allowed=False,
                requires_approval=True,
                denial_reasons=[],
                approval_requirement=approval_req,
                metadata={
                    "evaluation_stage": "approval",
                    "required_role": approval_req.required_role.value,
                },
            )
            logger.info(
                "tool_approval_required",
                tool_slug=check.tool_slug,
                risk=check.tool_risk_level.value,
                side_effect=check.tool_side_effect.value,
                required_role=approval_req.required_role.value,
            )
            return decision

        # 4. All checks passed — ALLOWED
        decision = ToolPermissionDecision(
            tool_slug=check.tool_slug,
            tool_version=check.tool_version,
            allowed=True,
            requires_approval=False,
            denial_reasons=[],
            metadata={"evaluation_stage": "complete"},
        )
        logger.debug(
            "tool_permission_granted",
            tool_slug=check.tool_slug,
        )
        return decision

    def enforce(self, check: ToolPermissionCheck) -> ToolPermissionDecision:
        """Evaluate and raise exceptions if the tool is not permitted.

        Convenience wrapper around evaluate() that raises typed exceptions
        for immediate use in the Tool Execution Engine.
        """
        decision = self.evaluate(check)

        if decision.is_denied:
            raise ToolPermissionDeniedError(
                f"Tool '{check.tool_slug}' denied: "
                + ", ".join(r.value for r in decision.denial_reasons),
                metadata={
                    "tool_slug": check.tool_slug,
                    "denial_reasons": [r.value for r in decision.denial_reasons],
                },
            )

        if decision.requires_approval and decision.approval_requirement:
            raise ToolApprovalRequiredError(
                f"Tool '{check.tool_slug}' requires approval: "
                + decision.approval_requirement.reason,
                approval_request_id="pending",  # Will be set by ApprovalService
                metadata={
                    "tool_slug": check.tool_slug,
                    "required_role": decision.approval_requirement.required_role.value,
                    "risk_level": decision.approval_requirement.risk_level.value,
                },
            )

        return decision