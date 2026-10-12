"""
Memory Permission Engine (C4 §7, §8, §33-34).

Evaluates whether a specific agent/user can read, write, promote, or delete
memories at a given scope. Produces auditable decisions.

Design:
    - Organization boundary is ALWAYS enforced (hardcoded, not policy-configurable)
    - Scope access is policy-driven (configurable per org/agent)
    - Scope_id matching is enforced for project/task scopes
    - Cross-scope reads require explicit policy permission

Architecture:
    MemoryStore.write/get/update/archive
        ↓
    MemoryPermissionEngine.authorize(...)
        ↓
    MemoryAccessDecision (ALLOWED | DENIED)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from schemas.domain.enums import MemoryScope

from core.observability.logging import get_logger
from core.memory.permissions.policies import MemoryAccessPolicy, MemoryScopePolicy


logger = get_logger("dsrt.memory.permissions")


class MemoryAction(str, Enum):
    """Memory access actions."""
    READ = "READ"
    WRITE = "WRITE"
    PROMOTE = "PROMOTE"
    DELETE = "DELETE"
    RETRIEVE = "RETRIEVE"


class MemoryDenialReason(str, Enum):
    """Reasons a memory access was denied."""
    ORGANIZATION_MISMATCH = "ORGANIZATION_MISMATCH"
    SCOPE_NOT_READABLE = "SCOPE_NOT_READABLE"
    SCOPE_NOT_WRITABLE = "SCOPE_NOT_WRITABLE"
    SCOPE_NOT_PROMOTABLE = "SCOPE_NOT_PROMOTABLE"
    SCOPE_NOT_DELETABLE = "SCOPE_NOT_DELETABLE"
    SCOPE_ID_MISMATCH = "SCOPE_ID_MISMATCH"
    CROSS_PROJECT_DENIED = "CROSS_PROJECT_DENIED"
    ORG_WRITE_REQUIRES_APPROVAL = "ORG_WRITE_REQUIRES_APPROVAL"


@dataclass(frozen=True)
class MemoryAccessDecision:
    """Immutable, auditable result of a memory permission check."""
    allowed: bool
    action: MemoryAction
    scope: MemoryScope
    denial_reason: MemoryDenialReason | None = None
    metadata: dict[str, Any] | None = None


class MemoryPermissionEngine:
    """Evaluates memory access permissions."""

    def __init__(
        self,
        scope_policy: MemoryScopePolicy | None = None,
        agent_policy: MemoryAccessPolicy | None = None,
    ) -> None:
        self._scope_policy = scope_policy or MemoryScopePolicy()
        self._agent_policy = agent_policy or self._scope_policy.default_agent_policy

    def authorize(
        self,
        *,
        action: MemoryAction,
        requester_org_id: str,
        memory_org_id: str,
        scope: MemoryScope,
        scope_id: str | None = None,
        requester_scope_ids: list[str] | None = None,
    ) -> MemoryAccessDecision:
        """Evaluate a memory access request.

        Args:
            action: The requested operation (READ/WRITE/PROMOTE/DELETE).
            requester_org_id: The organization of the requester.
            memory_org_id: The organization that owns the memory.
            scope: The scope of the memory being accessed.
            scope_id: The specific scope_id of the memory (e.g. project_id, task_id).
            requester_scope_ids: Scope IDs the requester has access to
                (e.g. their current project_id, task_id).

        Returns:
            MemoryAccessDecision with allowed=True or denial reason.
        """
        # --- 1. Organization boundary (ABSOLUTE — never bypassed) ---
        if requester_org_id != memory_org_id:
            decision = MemoryAccessDecision(
                allowed=False,
                action=action,
                scope=scope,
                denial_reason=MemoryDenialReason.ORGANIZATION_MISMATCH,
            )
            logger.warning(
                "memory_access_denied",
                action=action.value,
                reason="ORGANIZATION_MISMATCH",
                requester_org=requester_org_id,
                memory_org=memory_org_id,
            )
            return decision

        # --- 2. Scope access check ---
        scope_allowed = self._check_scope_access(action, scope)
        if not scope_allowed:
            reason = self._denial_reason_for_action(action)
            decision = MemoryAccessDecision(
                allowed=False,
                action=action,
                scope=scope,
                denial_reason=reason,
            )
            logger.warning(
                "memory_access_denied",
                action=action.value,
                reason=reason.value,
                scope=scope.value,
            )
            return decision

        # --- 3. Scope ID matching (for project/task scopes) ---
        if scope_id and requester_scope_ids is not None:
            if scope in (MemoryScope.PROJECT, MemoryScope.TASK):
                if scope_id not in requester_scope_ids:
                    if scope == MemoryScope.PROJECT and not self._scope_policy.allow_cross_project_read:
                        decision = MemoryAccessDecision(
                            allowed=False,
                            action=action,
                            scope=scope,
                            denial_reason=MemoryDenialReason.CROSS_PROJECT_DENIED,
                        )
                        logger.warning(
                            "memory_access_denied",
                            action=action.value,
                            reason="CROSS_PROJECT_DENIED",
                            scope_id=scope_id,
                        )
                        return decision

                    if scope == MemoryScope.TASK and not self._scope_policy.allow_cross_task_read:
                        decision = MemoryAccessDecision(
                            allowed=False,
                            action=action,
                            scope=scope,
                            denial_reason=MemoryDenialReason.SCOPE_ID_MISMATCH,
                        )
                        return decision

        # --- 4. Organization-scope write protection ---
        if (
            action == MemoryAction.WRITE
            and scope == MemoryScope.ORGANIZATION
            and self._scope_policy.require_approval_for_org_write
        ):
            decision = MemoryAccessDecision(
                allowed=False,
                action=action,
                scope=scope,
                denial_reason=MemoryDenialReason.ORG_WRITE_REQUIRES_APPROVAL,
            )
            logger.info(
                "memory_org_write_requires_approval",
                action=action.value,
                scope=scope.value,
            )
            return decision

        # --- 5. ALLOWED ---
        return MemoryAccessDecision(
            allowed=True,
            action=action,
            scope=scope,
        )

    def _check_scope_access(
        self, action: MemoryAction, scope: MemoryScope,
    ) -> bool:
        """Check if the agent policy allows the action at the given scope."""
        if action in (MemoryAction.READ, MemoryAction.RETRIEVE):
            return scope in self._agent_policy.readable_scopes
        elif action == MemoryAction.WRITE:
            return scope in self._agent_policy.writable_scopes
        elif action == MemoryAction.PROMOTE:
            return scope in self._agent_policy.promotable_scopes
        elif action == MemoryAction.DELETE:
            return scope in self._agent_policy.deletable_scopes
        return False

    @staticmethod
    def _denial_reason_for_action(action: MemoryAction) -> MemoryDenialReason:
        if action in (MemoryAction.READ, MemoryAction.RETRIEVE):
            return MemoryDenialReason.SCOPE_NOT_READABLE
        elif action == MemoryAction.WRITE:
            return MemoryDenialReason.SCOPE_NOT_WRITABLE
        elif action == MemoryAction.PROMOTE:
            return MemoryDenialReason.SCOPE_NOT_PROMOTABLE
        elif action == MemoryAction.DELETE:
            return MemoryDenialReason.SCOPE_NOT_DELETABLE
        return MemoryDenialReason.SCOPE_NOT_READABLE