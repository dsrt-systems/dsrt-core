"""
DSRT Permission Engine.

Evaluates the C1 §36 authorization chain:

    User → Organization → Permission → Task → Execution → Agent → Capability → Tool

For C1.4 we only implement the User + Organization + basic Resource stages.
Agent/Capability/Tool stages become active once those subsystems land in
C1.5+, but the API surface here is stable — future stages plug in without
changing callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.api.errors.exceptions import AuthorizationError
from core.security.context import SecurityContext
from schemas.domain.enums import OrganizationRole


class Action(str, Enum):
    """Coarse-grained action categories authorized at the org level."""

    # Read operations.
    READ_ORGANIZATION = "read_organization"
    READ_TASK = "read_task"
    READ_EXECUTION = "read_execution"
    READ_ARTIFACT = "read_artifact"

    # Write operations.
    CREATE_TASK = "create_task"
    CANCEL_EXECUTION = "cancel_execution"

    # Administrative.
    MANAGE_ORGANIZATION = "manage_organization"
    MANAGE_MEMBERS = "manage_members"


@dataclass(frozen=True)
class PermissionCheck:
    """The subject of a permission evaluation."""

    action: Action
    organization_id: str
    # Future-stage identifiers, kept optional for forward compatibility.
    task_id: str | None = None
    execution_id: str | None = None
    agent_slug: str | None = None
    capability_slug: str | None = None
    tool_slug: str | None = None


# Minimum role required to perform each action.
_MIN_ROLE: dict[Action, OrganizationRole] = {
    Action.READ_ORGANIZATION: OrganizationRole.VIEWER,
    Action.READ_TASK: OrganizationRole.VIEWER,
    Action.READ_EXECUTION: OrganizationRole.VIEWER,
    Action.READ_ARTIFACT: OrganizationRole.VIEWER,
    Action.CREATE_TASK: OrganizationRole.MEMBER,
    Action.CANCEL_EXECUTION: OrganizationRole.MEMBER,
    Action.MANAGE_ORGANIZATION: OrganizationRole.OWNER,
    Action.MANAGE_MEMBERS: OrganizationRole.ADMIN,
}


class PermissionEngine:
    """Evaluates authorization decisions."""

    def evaluate(
        self, context: SecurityContext, check: PermissionCheck,
    ) -> None:
        """Raise AuthorizationError if the caller is not permitted.

        Returns None on success. Never returns a permission decision object —
        the absence of an exception IS the permission grant.
        """
        # Stage 1: Organization membership.
        if not context.is_member_of(check.organization_id):
            raise AuthorizationError(
                "You are not a member of the target organization.",
                metadata={"action": check.action.value},
            )

        # Stage 2: Role sufficiency.
        minimum = _MIN_ROLE[check.action]
        if not context.has_role(check.organization_id, minimum):
            raise AuthorizationError(
                f"Action '{check.action.value}' requires role "
                f"'{minimum.value}' or higher.",
                metadata={
                    "action": check.action.value,
                    "required_role": minimum.value,
                },
            )

        # Stages 3–6: Task / Execution / Agent / Capability / Tool.
        # Placeholders — become active in later C1 sub-phases.
        # The evaluation order (§36) is fixed:
        #     org → task → execution → agent → capability → tool.
        return None


_engine = PermissionEngine()


def get_permission_engine() -> PermissionEngine:
    return _engine
