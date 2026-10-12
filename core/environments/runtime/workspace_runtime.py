"""
Workspace Environment Runtime (C3 §33-34, §37-38).

The default environment runtime. Wraps the C3.8 WorkspaceManager to
provide a lifecycle-managed environment backed by an isolated directory
on the host filesystem.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.observability.logging import get_logger
from core.tools.environments.workspace.manager import WorkspaceManager


logger = get_logger("dsrt.environments.workspace_runtime")


class WorkspaceEnvironmentRuntime:
    """Default environment runtime backed by the virtual workspace."""

    runtime_type = "FILE"

    def __init__(self, workspace_root: str | None = None) -> None:
        self._ws = WorkspaceManager(root=workspace_root)

    async def provision(
        self,
        instance_id: str,
        organization_id: str,
        execution_id: str | None,
        resource_profile: dict[str, Any],
        network_policy: dict[str, Any],
        filesystem_policy: dict[str, Any],
    ) -> dict[str, Any]:
        """Create the workspace directory structure."""
        exe_id = execution_id or instance_id
        ws_path = self._ws.create_workspace(organization_id, exe_id)

        logger.info(
            "workspace_environment_provisioned",
            instance_id=instance_id,
            workspace_path=str(ws_path),
        )

        return {
            "workspace_path": str(ws_path),
            "runtime_reference": f"ws://{organization_id}/{exe_id}",
            "provisioned_at": datetime.now(timezone.utc).isoformat(),
        }

    async def start(
        self,
        instance_id: str,
        runtime_reference: str | None = None,
    ) -> None:
        """Workspace environments are always ready after provisioning."""
        logger.debug("workspace_environment_started", instance_id=instance_id)

    async def health(
        self,
        instance_id: str,
        runtime_reference: str | None = None,
    ) -> dict[str, Any]:
        """Check workspace directory existence and basic health."""
        # Parse org/exe from runtime_reference
        if runtime_reference and runtime_reference.startswith("ws://"):
            parts = runtime_reference[5:].split("/")
            if len(parts) >= 2:
                org_id, exe_id = parts[0], parts[1]
                exists = self._ws.workspace_exists(org_id, exe_id)
                return {
                    "status": "healthy" if exists else "unhealthy",
                    "workspace_exists": exists,
                    "instance_id": instance_id,
                }

        return {
            "status": "unknown",
            "workspace_exists": False,
            "instance_id": instance_id,
        }

    async def snapshot(
        self,
        instance_id: str,
        runtime_reference: str | None = None,
    ) -> dict[str, Any]:
        """Capture a lightweight metadata snapshot of the workspace.

        Full disk-level snapshotting arrives in C7. For C3.10, we capture
        a file listing hash as a basic state fingerprint.
        """
        if runtime_reference and runtime_reference.startswith("ws://"):
            parts = runtime_reference[5:].split("/")
            if len(parts) >= 2:
                org_id, exe_id = parts[0], parts[1]
                try:
                    entries = self._ws.list_directory(
                        "/workspace/working", org_id, exe_id,
                    )
                    state_str = json.dumps(
                        sorted(e["name"] for e in entries), sort_keys=True,
                    )
                    state_hash = hashlib.sha256(
                        state_str.encode("utf-8")
                    ).hexdigest()
                    total_size = sum(e.get("size_bytes", 0) for e in entries)
                except Exception:
                    state_hash = "empty"
                    total_size = 0

                return {
                    "state_hash": state_hash,
                    "total_size_bytes": total_size,
                    "snapshot_type": "metadata",
                    "instance_id": instance_id,
                }

        return {
            "state_hash": "unknown",
            "total_size_bytes": 0,
            "snapshot_type": "metadata",
            "instance_id": instance_id,
        }

    async def reset(
        self,
        instance_id: str,
        runtime_reference: str | None = None,
    ) -> None:
        """Reset the workspace by destroying and recreating it."""
        if runtime_reference and runtime_reference.startswith("ws://"):
            parts = runtime_reference[5:].split("/")
            if len(parts) >= 2:
                org_id, exe_id = parts[0], parts[1]
                self._ws.destroy_workspace(org_id, exe_id)
                self._ws.create_workspace(org_id, exe_id)
                logger.info(
                    "workspace_environment_reset",
                    instance_id=instance_id,
                )

    async def destroy(
        self,
        instance_id: str,
        runtime_reference: str | None = None,
    ) -> None:
        """Destroy the workspace and release disk resources."""
        if runtime_reference and runtime_reference.startswith("ws://"):
            parts = runtime_reference[5:].split("/")
            if len(parts) >= 2:
                org_id, exe_id = parts[0], parts[1]
                self._ws.destroy_workspace(org_id, exe_id)
                logger.info(
                    "workspace_environment_destroyed",
                    instance_id=instance_id,
                )