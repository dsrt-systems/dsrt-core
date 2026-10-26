"""
Filesystem Component (C7 §10, §13, §24-25).

Wraps the C3 WorkspaceManager to provide isolated filesystem
access within a World instance.

Capabilities:
  - Isolated workspace per execution
  - Path traversal prevention
  - Symlink rejection
  - Size limits
  - Subdirectory enforcement
"""

from __future__ import annotations

from typing import Any

from core.observability.logging import get_logger
from core.tools.environments.workspace.manager import WorkspaceManager
from core.worlds.components.component import (
    BaseWorldComponent,
    ComponentContext,
    ComponentHealth,
    ComponentSnapshot,
)


logger = get_logger("dsrt.worlds.components.filesystem")


class FilesystemComponent(BaseWorldComponent):
    """Isolated filesystem component backed by C3 WorkspaceManager."""

    def __init__(self, slug: str = "workspace") -> None:
        self._slug = slug
        self._workspace_mgr: WorkspaceManager | None = None

    @property
    def component_type(self) -> str:
        return "filesystem"

    @property
    def slug(self) -> str:
        return self._slug

    def _get_workspace_mgr(self) -> WorkspaceManager:
        if self._workspace_mgr is None:
            self._workspace_mgr = WorkspaceManager()
        return self._workspace_mgr

    async def provision(self, context: ComponentContext) -> bool:
        """Create the isolated workspace directory structure."""
        try:
            mgr = self._get_workspace_mgr()
            ws_path = mgr.create_workspace(
                organization_id=context.organization_id,
                execution_id=context.execution_id or context.world_instance_id,
            )
            context.workspace_path = str(ws_path)
            logger.info(
                "filesystem_provisioned",
                world_instance=context.world_instance_id,
                path=str(ws_path),
            )
            return True
        except Exception as e:
            logger.error(
                "filesystem_provision_failed",
                error=str(e),
            )
            return False

    async def start(self, context: ComponentContext) -> bool:
        """Verify the workspace exists and is accessible."""
        try:
            mgr = self._get_workspace_mgr()
            exists = mgr.workspace_exists(
                organization_id=context.organization_id,
                execution_id=context.execution_id or context.world_instance_id,
            )
            return exists
        except Exception:
            return False

    async def health(self, context: ComponentContext) -> ComponentHealth:
        """Check filesystem health."""
        try:
            mgr = self._get_workspace_mgr()
            exists = mgr.workspace_exists(
                organization_id=context.organization_id,
                execution_id=context.execution_id or context.world_instance_id,
            )
            if exists:
                return ComponentHealth(
                    component_id=self.slug,
                    component_type=self.component_type,
                    status="healthy",
                    detail="Workspace accessible",
                )
            return ComponentHealth(
                component_id=self.slug,
                component_type=self.component_type,
                status="unhealthy",
                detail="Workspace not found",
            )
        except Exception as e:
            return ComponentHealth(
                component_id=self.slug,
                component_type=self.component_type,
                status="unhealthy",
                detail=str(e),
            )

    async def snapshot(self, context: ComponentContext) -> ComponentSnapshot:
        """Capture filesystem state (file listing + sizes)."""
        try:
            mgr = self._get_workspace_mgr()
            listing = mgr.list_directory(
                "/workspace",
                organization_id=context.organization_id,
                execution_id=context.execution_id or context.world_instance_id,
            )
            return ComponentSnapshot(
                component_id=self.slug,
                component_type=self.component_type,
                data={"file_count": len(listing), "files": listing[:50]},
            )
        except Exception:
            return ComponentSnapshot(
                component_id=self.slug,
                component_type=self.component_type,
            )

    async def destroy(self, context: ComponentContext) -> bool:
        """Remove the workspace directory."""
        try:
            mgr = self._get_workspace_mgr()
            mgr.destroy_workspace(
                organization_id=context.organization_id,
                execution_id=context.execution_id or context.world_instance_id,
            )
            logger.info(
                "filesystem_destroyed",
                world_instance=context.world_instance_id,
            )
            return True
        except Exception as e:
            logger.warning(
                "filesystem_destroy_failed",
                error=str(e),
            )
            return False

    def get_capabilities(self) -> list[str]:
        return ["filesystem", "file_read", "file_write", "workspace"]