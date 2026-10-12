"""
filesystem.stat — Get file metadata from the virtual workspace (C3 §24).
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

from core.storage.identifiers import IdPrefix, new_id
from core.tools.builtins._base import BuiltinToolBase
from core.tools.environments.workspace.manager import WorkspaceError, WorkspaceManager


class FilesystemStatTool(BuiltinToolBase):
    identity = ToolIdentity(
        slug="filesystem.stat", name="Filesystem Stat",
        version="1.0.0", contract_version="1.0", publisher="dsrt", category="filesystem",
    )
    manifest = ToolManifest(
        identity=identity,
        description="Get metadata (size, type, timestamps) for a workspace path.",
        capabilities=[ToolCapabilityDeclaration(slug="filesystem.stat")],
        permissions=ToolPermissionDeclaration(
            filesystem=ToolFilesystemPermission(read=True),
        ),
        risk_level=ToolRiskLevel.LOW,
        side_effect=SideEffectClass.READ,
        limits=ToolLimits(timeout_seconds=5),
        retry=ToolRetryPolicy(allowed=False, max_attempts=1),
        input_schema={
            "type": "object", "required": ["path"],
            "properties": {"path": {"type": "string"}},
        },
        output_schema={"type": "object"},
    )

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        start_time = time.perf_counter()
        path = (request.arguments or {}).get("path", "")
        if not path:
            return self._error(request, start_time, "TOOL_INVALID_ARGUMENT", "Missing 'path'.")

        ws = WorkspaceManager()
        try:
            stat_info = ws.stat_file(path, request.organization_id, request.execution_id)
        except WorkspaceError as e:
            return self._error(request, start_time, "TOOL_RUNTIME_FAILURE", str(e))

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        now = datetime.now(timezone.utc)

        observation = ToolObservation(
            observation_id=new_id(IdPrefix.TOOL_OBSERVATION),
            observation_type=ObservationType.FILE_METADATA,
            content=stat_info,
            summary=f"Stat {path}: {stat_info.get('type', 'unknown')}, {stat_info.get('size_bytes', 0)} bytes",
            source=self.identity.slug, timestamp=now,
            provenance={"tool_slug": self.identity.slug, "execution_id": request.execution_id},
        )

        return ToolExecutionResult(
            request_id=request.request_id, tool_execution_id=request.request_id,
            tool_slug=self.identity.slug, tool_version=self.identity.version,
            status=ToolExecutionStatus.COMPLETED,
            output=stat_info, observations=[observation], artifact_ids=[], errors=[],
            usage=ToolUsage(duration_ms=duration_ms),
            duration_ms=duration_ms, attempt=request.attempt,
            started_at=now, completed_at=now,
        )

    def _error(self, request, start_time, code, msg):
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolExecutionResult(
            request_id=request.request_id, tool_execution_id=request.request_id,
            tool_slug=self.identity.slug, tool_version=self.identity.version,
            status=ToolExecutionStatus.FAILED,
            output=None, observations=[], artifact_ids=[],
            errors=[ToolExecutionError(code=code, message=msg)],
            usage=ToolUsage(duration_ms=duration_ms),
            duration_ms=duration_ms, attempt=request.attempt,
        )