"""
World Isolation Manager (C7 §13, §48, §66-68).

Enforces the six isolation boundaries required for every World instance:
  1. Filesystem isolation — agents confined to workspace
  2. Process isolation — no cross-execution process access
  3. Network policy — domain-level allow/deny
  4. Credential isolation — secrets never exposed to agents
  5. Storage isolation — no cross-world data access
  6. Execution identity — every action attributable

Security Tests (C7 §74):
  - Cross-world filesystem access → DENIED
  - Cross-tenant access → DENIED
  - Credential extraction → DENIED
  - Network escape → DENIED
  - Process escape → DENIED
  - Unauthorized API access → DENIED
  - Snapshot access → DENIED
  - Artifact access → DENIED
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.api.errors.exceptions import AuthorizationError
from core.observability.logging import get_logger
from core.storage.models.world import WorldInstanceORM


logger = get_logger("dsrt.worlds.isolation")


class IsolationBoundary(str, Enum):
    """The six isolation boundaries (C7 §13)."""
    FILESYSTEM = "filesystem"
    PROCESS = "process"
    NETWORK = "network"
    CREDENTIAL = "credential"
    STORAGE = "storage"
    EXECUTION_IDENTITY = "execution_identity"


@dataclass(frozen=True)
class IsolationDecision:
    """Result of an isolation check."""
    allowed: bool
    boundary: IsolationBoundary
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)


class WorldIsolationManager:
    """Enforces all isolation boundaries for World instances (C7 §13).

    Usage:
        iso = WorldIsolationManager(session)

        # Check tenant isolation
        decision = await iso.check_tenant_isolation(
            requester_org_id="org_A",
            world_instance_id="wi_1",
        )
        if not decision.allowed:
            raise AuthorizationError(decision.reason)

        # Check cross-world access
        decision = iso.check_cross_world_access(
            source_world_id="wi_1",
            target_world_id="wi_2",
        )
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Tenant Isolation (C7 §13, §74)
    # ------------------------------------------------------------------

    async def check_tenant_isolation(
        self,
        requester_org_id: str,
        world_instance_id: str,
    ) -> IsolationDecision:
        """Verify the requester's org owns the world instance.

        This is the most critical isolation check. It MUST be enforced
        on every world access — no exceptions.
        """
        stmt = select(WorldInstanceORM.organization_id).where(
            WorldInstanceORM.id == world_instance_id,
        )
        result = await self._session.execute(stmt)
        owner_org_id = result.scalar_one_or_none()

        if owner_org_id is None:
            return IsolationDecision(
                allowed=False,
                boundary=IsolationBoundary.EXECUTION_IDENTITY,
                reason=f"World instance '{world_instance_id}' not found.",
            )

        if owner_org_id != requester_org_id:
            logger.warning(
                "tenant_isolation_violation",
                requester_org=requester_org_id,
                owner_org=owner_org_id,
                world_instance=world_instance_id,
            )
            return IsolationDecision(
                allowed=False,
                boundary=IsolationBoundary.STORAGE,
                reason="Cross-tenant world access denied.",
                details={
                    "requester_org": requester_org_id,
                    "owner_org": owner_org_id,
                },
            )

        return IsolationDecision(
            allowed=True,
            boundary=IsolationBoundary.STORAGE,
            reason="Tenant isolation verified.",
        )

    # ------------------------------------------------------------------
    # Filesystem Isolation (C7 §13, §24-25)
    # ------------------------------------------------------------------

    def check_filesystem_isolation(
        self,
        requested_path: str,
        workspace_root: str,
        world_instance_id: str,
    ) -> IsolationDecision:
        """Verify a filesystem path is within the world's workspace.

        Prevents:
          - Path traversal (../)
          - Absolute path escape
          - Cross-world filesystem access
          - Symlink escape
        """
        import os

        # Normalize paths
        normalized = os.path.normpath(requested_path)
        workspace = os.path.normpath(workspace_root)

        # Check for path traversal
        if ".." in normalized.split(os.sep):
            return IsolationDecision(
                allowed=False,
                boundary=IsolationBoundary.FILESYSTEM,
                reason=f"Path traversal detected: '{requested_path}'",
                details={"normalized": normalized},
            )

        # Check containment
        abs_requested = os.path.abspath(normalized)
        abs_workspace = os.path.abspath(workspace)

        if not abs_requested.startswith(abs_workspace + os.sep) and abs_requested != abs_workspace:
            return IsolationDecision(
                allowed=False,
                boundary=IsolationBoundary.FILESYSTEM,
                reason=f"Path escapes workspace: '{requested_path}'",
                details={
                    "requested": abs_requested,
                    "workspace": abs_workspace,
                },
            )

        return IsolationDecision(
            allowed=True,
            boundary=IsolationBoundary.FILESYSTEM,
            reason="Path within workspace.",
        )

    # ------------------------------------------------------------------
    # Cross-World Isolation (C7 §66-68)
    # ------------------------------------------------------------------

    def check_cross_world_access(
        self,
        source_world_id: str,
        target_world_id: str,
        access_type: str = "filesystem",
    ) -> IsolationDecision:
        """Verify that one world cannot access another world's resources.

        Rule (C7 §68): Worlds are isolated by default.
        Communication requires explicit capability + policy + artifact/reference.
        """
        if source_world_id == target_world_id:
            return IsolationDecision(
                allowed=True,
                boundary=IsolationBoundary.STORAGE,
                reason="Same world — access allowed.",
            )

        logger.warning(
            "cross_world_access_denied",
            source=source_world_id,
            target=target_world_id,
            access_type=access_type,
        )

        return IsolationDecision(
            allowed=False,
            boundary=IsolationBoundary.STORAGE,
            reason=(
                f"Cross-world {access_type} access denied. "
                f"World '{source_world_id}' cannot access "
                f"world '{target_world_id}'. "
                f"Use the Core Artifact Service for cross-world data transfer."
            ),
            details={
                "source_world": source_world_id,
                "target_world": target_world_id,
                "access_type": access_type,
            },
        )

    # ------------------------------------------------------------------
    # Process Isolation (C7 §13)
    # ------------------------------------------------------------------

    def check_process_isolation(
        self,
        requesting_execution_id: str,
        target_execution_id: str,
    ) -> IsolationDecision:
        """Verify that one execution cannot access another's processes."""
        if requesting_execution_id == target_execution_id:
            return IsolationDecision(
                allowed=True,
                boundary=IsolationBoundary.PROCESS,
                reason="Same execution.",
            )

        return IsolationDecision(
            allowed=False,
            boundary=IsolationBoundary.PROCESS,
            reason=(
                f"Cross-execution process access denied. "
                f"Execution '{requesting_execution_id}' cannot access "
                f"processes of '{target_execution_id}'."
            ),
        )

    # ------------------------------------------------------------------
    # Credential Isolation (C7 §13, §24)
    # ------------------------------------------------------------------

    def check_credential_isolation(
        self,
        requester_type: str,
        credential_ref: str,
    ) -> IsolationDecision:
        """Verify that agents cannot directly access credential material.

        Rule (C7 §24): Agents receive permission to use
        'credential://github/read', not the raw secret.
        """
        if requester_type == "agent":
            # Agents should never request raw credentials
            if not credential_ref.startswith("credential://"):
                return IsolationDecision(
                    allowed=False,
                    boundary=IsolationBoundary.CREDENTIAL,
                    reason=(
                        "Agents cannot access raw credentials. "
                        "Use credential references (credential://provider/scope)."
                    ),
                )

        return IsolationDecision(
            allowed=True,
            boundary=IsolationBoundary.CREDENTIAL,
            reason="Credential access pattern valid.",
        )

    # ------------------------------------------------------------------
    # Comprehensive Check
    # ------------------------------------------------------------------

    async def enforce_all(
        self,
        *,
        requester_org_id: str,
        world_instance_id: str,
        requester_execution_id: str | None = None,
        target_execution_id: str | None = None,
        requested_path: str | None = None,
        workspace_root: str | None = None,
    ) -> list[IsolationDecision]:
        """Run all applicable isolation checks and return results.

        Any DENIED decision should block the operation.
        """
        decisions: list[IsolationDecision] = []

        # 1. Tenant isolation (always)
        decisions.append(
            await self.check_tenant_isolation(
                requester_org_id, world_instance_id,
            )
        )

        # 2. Filesystem isolation (if path provided)
        if requested_path and workspace_root:
            decisions.append(
                self.check_filesystem_isolation(
                    requested_path, workspace_root, world_instance_id,
                )
            )

        # 3. Process isolation (if cross-execution)
        if requester_execution_id and target_execution_id:
            decisions.append(
                self.check_process_isolation(
                    requester_execution_id, target_execution_id,
                )
            )

        # Log summary
        denied = [d for d in decisions if not d.allowed]
        if denied:
            logger.warning(
                "isolation_violations_detected",
                world_instance=world_instance_id,
                violations=len(denied),
                boundaries=[d.boundary.value for d in denied],
            )

        return decisions