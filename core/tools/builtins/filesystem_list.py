"""
filesystem.list — List directory contents in the virtual workspace (C3 §24).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from schemas.domain.enums import (
    ObservationType,
    SideEffectClass,
    ToolExecutionStatus,
    ToolRiskLevel,
)
from schemas.domain.tool import (
    ToolCapabilityDeclaration,
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolFilesystemPermission,
    ToolIdentity,
    ToolLimits,
    ToolManifest,
    ToolObservation,
    ToolPermissionDeclaration,
    ToolRetryPolicy,
    ToolUsage,
)

from core.observability.logging import get_logger
from core.storage.identifiers import IdPrefix, new_id
from core.tools.builtins._base import BuiltinToolBase
from core.tools.environments.workspace.manager import WorkspaceError, WorkspaceManager


logger = get_logger("dsrt.tools.filesystem.list")


class FilesystemListTool(BuiltinToolBase):
    identity = ToolIdentity(
        slug="filesystem.list",
        name="Filesystem List",
        version="1.0.0",
        contract_version="1.0",
        publisher="dsrt",
        category="filesystem",
    )

    manifest = ToolManifest(
        identity=identity,
        description="List files and directories in a workspace path.",
        capabilities=[ToolCapabilityDeclaration(slug="filesystem.list")],
        permissions=ToolPermissionDeclaration(
            filesystem=ToolFilesystemPermission(read=True),
        ),
        risk_level=ToolRiskLevel.LOW,
        side_effect=SideEffectClass.READ,
        limits=ToolLimits(timeout_seconds=10),
        retry=ToolRetryPolicy(allowed=False, max_attempts=1),
        input_schema={
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {"type": "string", "default": "/workspace/working"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "entries": {"type": "array"},
                "count": {"type": "integer"},
            },
        },
    )

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        start_time = time.perf_counter()
        args = request.arguments or {}
        path = args.get("path", "/workspace/working")

        ws = WorkspaceManager()
        try:
            entries = ws.list_directory(
                path, request.organization_id, request.execution_id,
            )
        except WorkspaceError as e:
            return self._error(request, start_time, "TOOL_RUNTIME_FAILURE", str(e))
        except Exception as e:
            return self._error(request, start_time, "TOOL_RUNTIME_FAILURE", str(e))

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        now = datetime.now(timezone.utc)

        output = {"path": path, "entries": entries, "count": len(entries)}

        observation = ToolObservation(
            observation_id=new_id(IdPrefix.TOOL_OBSERVATION),
            observation_type=ObservationType.DIRECTORY_LISTING,
            content=output,
            summary=f"Listed {len(entries)} entries in {path}",
            source=self.identity.slug,
            timestamp=now,
            provenance={
                "tool_slug": self.identity.slug,
                "execution_id": request.execution_id,
            },
        )

        return ToolExecutionResult(
            request_id=request.request_id,
            tool_execution_id=request.request_id,
            tool_slug=self.identity.slug,
            tool_version=self.identity.version,
            status=ToolExecutionStatus.COMPLETED,
            output=output,
            observations=[observation],
            artifact_ids=[],
            errors=[],
            usage=ToolUsage(duration_ms=duration_ms),
            duration_ms=duration_ms,
            attempt=request.attempt,
            started_at=now,
            completed_at=now,
        )

    def _error(self, request, start_time, code, msg):
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolExecutionResult(
            request_id=request.request_id,
            tool_execution_id=request.request_id,
            tool_slug=self.identity.slug,
            tool_version=self.identity.version,
            status=ToolExecutionStatus.FAILED,
            output=None, observations=[], artifact_ids=[],
            errors=[ToolExecutionError(code=code, message=msg)],
            usage=ToolUsage(duration_ms=duration_ms),
            duration_ms=duration_ms, attempt=request.attempt,
        )