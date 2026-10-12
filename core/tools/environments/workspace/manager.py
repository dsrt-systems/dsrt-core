"""
Workspace Manager — Isolated Virtual Filesystem (C3 §24-25).

Creates, manages, and destroys per-execution workspaces on the host
filesystem. Agents interact with virtual paths (/workspace/input, etc.)
that are resolved to real, isolated host paths.

Security guarantees:
  1. Path traversal prevention — ".." and absolute paths rejected
  2. Symlink prevention — symlinks cannot escape the workspace
  3. Scope confinement — resolved path MUST be within workspace root
  4. Subdirectory enforcement — only input/working/output/temp allowed
  5. Zero cross-execution access — each execution gets its own directory
  6. Zero cross-org access — workspaces nested under org directories
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from core.api.errors.exceptions import ValidationError
from core.config import get_settings
from core.observability.logging import get_logger


logger = get_logger("dsrt.tools.workspace")

# The four allowed virtual subdirectories
ALLOWED_SUBDIRS = ("input", "working", "output", "temp")

# Maximum path depth to prevent abuse
_MAX_PATH_DEPTH = 20


class WorkspaceError(ValidationError):
    """Raised when a workspace operation violates security constraints."""
    pass


class WorkspaceManager:
    """Manages isolated virtual workspaces for DSRT executions."""

    def __init__(self, root: str | None = None) -> None:
        settings = get_settings()
        self._root = Path(root or settings.workspace_root).resolve()
        self._max_file_bytes = settings.workspace_max_file_size_mb * 1024 * 1024
        self._max_total_bytes = settings.workspace_max_total_size_mb * 1024 * 1024

    @property
    def root(self) -> Path:
        return self._root

    # ------------------------------------------------------------------
    # Workspace Lifecycle
    # ------------------------------------------------------------------

    def create_workspace(
        self, organization_id: str, execution_id: str,
    ) -> Path:
        """Create an isolated workspace for an execution.

        Returns the real host path to the workspace root.
        Creates the four standard subdirectories.
        """
        ws_path = self._workspace_path(organization_id, execution_id)

        if ws_path.exists():
            logger.debug(
                "workspace_already_exists",
                organization_id=organization_id,
                execution_id=execution_id,
                path=str(ws_path),
            )
            return ws_path

        ws_path.mkdir(parents=True, exist_ok=True)

        for subdir in ALLOWED_SUBDIRS:
            (ws_path / subdir).mkdir(exist_ok=True)

        logger.info(
            "workspace_created",
            organization_id=organization_id,
            execution_id=execution_id,
            path=str(ws_path),
        )
        return ws_path

    def destroy_workspace(
        self, organization_id: str, execution_id: str,
    ) -> bool:
        """Destroy an execution workspace and all its contents.

        Returns True if the workspace existed and was removed.
        """
        ws_path = self._workspace_path(organization_id, execution_id)

        if not ws_path.exists():
            return False

        # Safety: ensure the path is actually within our root
        self._assert_within_root(ws_path)

        shutil.rmtree(ws_path, ignore_errors=True)
        logger.info(
            "workspace_destroyed",
            organization_id=organization_id,
            execution_id=execution_id,
        )
        return True

    def workspace_exists(
        self, organization_id: str, execution_id: str,
    ) -> bool:
        return self._workspace_path(organization_id, execution_id).exists()

    # ------------------------------------------------------------------
    # Path Resolution (the security-critical core)
    # ------------------------------------------------------------------

    def resolve_virtual_path(
        self,
        virtual_path: str,
        organization_id: str,
        execution_id: str,
    ) -> Path:
        """Resolve a virtual workspace path to a real host path.

        Virtual paths look like: /workspace/working/report.md
        Real paths look like:   <root>/org_<id>/exe_<id>/working/report.md

        Raises WorkspaceError if the path is invalid or escapes the workspace.
        """
        # 1. Normalize the virtual path
        clean = virtual_path.strip()
        if not clean:
            raise WorkspaceError("Empty path.")

        # 2. Strip leading /workspace/ prefix if present
        if clean.startswith("/workspace/"):
            clean = clean[len("/workspace/"):]
        elif clean.startswith("/workspace"):
            clean = clean[len("/workspace"):]
            if clean.startswith("/"):
                clean = clean[1:]

        # 3. Reject absolute paths (after stripping /workspace/)
        if clean.startswith("/") or clean.startswith("\\"):
            raise WorkspaceError(
                f"Absolute paths not allowed: '{virtual_path}'"
            )

        # 4. Reject path traversal components
        parts = Path(clean).parts
        if ".." in parts:
            raise WorkspaceError(
                f"Path traversal not allowed: '{virtual_path}'"
            )

        # 5. Reject null bytes
        if "\x00" in clean:
            raise WorkspaceError("Null bytes not allowed in paths.")

        # 6. Enforce depth limit
        if len(parts) > _MAX_PATH_DEPTH:
            raise WorkspaceError(
                f"Path too deep ({len(parts)} levels): '{virtual_path}'"
            )

        # 7. Enforce subdirectory constraint
        if parts and parts[0] not in ALLOWED_SUBDIRS:
            raise WorkspaceError(
                f"Path must start with one of {ALLOWED_SUBDIRS}. "
                f"Got: '{parts[0]}'"
            )

        # 8. Build real path
        ws_path = self._workspace_path(organization_id, execution_id)
        real_path = (ws_path / clean).resolve()

        # 9. Final containment check — resolved path MUST be within workspace
        self._assert_within_workspace(real_path, ws_path, virtual_path)

        return real_path

    def virtual_to_relative(self, virtual_path: str) -> str:
        """Convert a virtual path to a workspace-relative path (no security checks)."""
        clean = virtual_path.strip()
        if clean.startswith("/workspace/"):
            return clean[len("/workspace/"):]
        if clean.startswith("/workspace"):
            return clean[len("/workspace"):].lstrip("/")
        return clean

    def real_to_virtual(
        self,
        real_path: Path,
        organization_id: str,
        execution_id: str,
    ) -> str:
        """Convert a real host path back to a virtual workspace path."""
        ws_path = self._workspace_path(organization_id, execution_id)
        try:
            relative = real_path.resolve().relative_to(ws_path.resolve())
            return f"/workspace/{relative.as_posix()}"
        except ValueError:
            return str(real_path)

    # ------------------------------------------------------------------
    # File Operations (safe wrappers)
    # ------------------------------------------------------------------

    def read_file(
        self,
        virtual_path: str,
        organization_id: str,
        execution_id: str,
        max_bytes: int | None = None,
    ) -> bytes:
        """Read a file from the workspace. Returns raw bytes."""
        real_path = self.resolve_virtual_path(
            virtual_path, organization_id, execution_id,
        )

        if not real_path.exists():
            raise WorkspaceError(f"File not found: '{virtual_path}'")
        if not real_path.is_file():
            raise WorkspaceError(f"Not a file: '{virtual_path}'")

        # Check symlink
        if real_path.is_symlink():
            raise WorkspaceError(f"Symlinks not allowed: '{virtual_path}'")

        limit = max_bytes or self._max_file_bytes
        file_size = real_path.stat().st_size
        if file_size > limit:
            raise WorkspaceError(
                f"File too large ({file_size} bytes > {limit} limit): '{virtual_path}'"
            )

        return real_path.read_bytes()

    def write_file(
        self,
        virtual_path: str,
        content: bytes | str,
        organization_id: str,
        execution_id: str,
    ) -> int:
        """Write content to a file in the workspace. Returns bytes written."""
        real_path = self.resolve_virtual_path(
            virtual_path, organization_id, execution_id,
        )

        if isinstance(content, str):
            data = content.encode("utf-8")
        else:
            data = content

        if len(data) > self._max_file_bytes:
            raise WorkspaceError(
                f"Content too large ({len(data)} bytes > {self._max_file_bytes} limit)."
            )

        # Ensure parent directory exists
        real_path.parent.mkdir(parents=True, exist_ok=True)

        # Final containment check on parent
        self._assert_within_workspace(
            real_path.parent,
            self._workspace_path(organization_id, execution_id),
            virtual_path,
        )

        real_path.write_bytes(data)
        return len(data)

    def list_directory(
        self,
        virtual_path: str,
        organization_id: str,
        execution_id: str,
    ) -> list[dict[str, Any]]:
        """List contents of a workspace directory."""
        real_path = self.resolve_virtual_path(
            virtual_path, organization_id, execution_id,
        )

        if not real_path.exists():
            raise WorkspaceError(f"Directory not found: '{virtual_path}'")
        if not real_path.is_dir():
            raise WorkspaceError(f"Not a directory: '{virtual_path}'")

        entries: list[dict[str, Any]] = []
        for item in sorted(real_path.iterdir()):
            try:
                stat = item.stat()
                entries.append({
                    "name": item.name,
                    "virtual_path": self.real_to_virtual(
                        item, organization_id, execution_id,
                    ),
                    "type": "directory" if item.is_dir() else "file",
                    "size_bytes": stat.st_size if item.is_file() else 0,
                    "modified_at": stat.st_mtime,
                })
            except OSError:
                # Skip inaccessible entries
                continue

        return entries

    def delete_file(
        self,
        virtual_path: str,
        organization_id: str,
        execution_id: str,
    ) -> bool:
        """Delete a file from the workspace."""
        real_path = self.resolve_virtual_path(
            virtual_path, organization_id, execution_id,
        )

        if not real_path.exists():
            return False
        if real_path.is_dir():
            raise WorkspaceError(
                f"Cannot delete directory with delete_file: '{virtual_path}'"
            )

        real_path.unlink()
        return True

    def move_file(
        self,
        src_virtual: str,
        dst_virtual: str,
        organization_id: str,
        execution_id: str,
    ) -> str:
        """Move/rename a file within the workspace."""
        src_real = self.resolve_virtual_path(
            src_virtual, organization_id, execution_id,
        )
        dst_real = self.resolve_virtual_path(
            dst_virtual, organization_id, execution_id,
        )

        if not src_real.exists():
            raise WorkspaceError(f"Source not found: '{src_virtual}'")

        dst_real.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_real), str(dst_real))
        return dst_virtual

    def stat_file(
        self,
        virtual_path: str,
        organization_id: str,
        execution_id: str,
    ) -> dict[str, Any]:
        """Get metadata for a workspace file or directory."""
        real_path = self.resolve_virtual_path(
            virtual_path, organization_id, execution_id,
        )

        if not real_path.exists():
            raise WorkspaceError(f"Path not found: '{virtual_path}'")

        stat = real_path.stat()
        return {
            "virtual_path": virtual_path,
            "type": "directory" if real_path.is_dir() else "file",
            "size_bytes": stat.st_size,
            "modified_at": stat.st_mtime,
            "created_at": stat.st_ctime,
            "is_symlink": real_path.is_symlink(),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _workspace_path(
        self, organization_id: str, execution_id: str,
    ) -> Path:
        """Build the real host path for an execution workspace."""
        return self._root / f"org_{organization_id}" / f"exe_{execution_id}"

    def _assert_within_root(self, path: Path) -> None:
        """Assert a path is within the global workspace root."""
        try:
            path.resolve().relative_to(self._root.resolve())
        except ValueError:
            raise WorkspaceError(
                f"Path escapes workspace root: '{path}'"
            )

    def _assert_within_workspace(
        self, real_path: Path, ws_path: Path, virtual_path: str,
    ) -> None:
        """Assert a resolved real path is within its execution workspace."""
        try:
            real_path.resolve().relative_to(ws_path.resolve())
        except ValueError:
            raise WorkspaceError(
                f"Path escapes workspace boundary: '{virtual_path}'"
            )