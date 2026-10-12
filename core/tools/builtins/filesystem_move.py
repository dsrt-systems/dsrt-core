"""
filesystem.move — Move/rename a file within the virtual workspace (C3 §24).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from schemas.domain.enums import (
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
    ToolPermissionDeclaration,
    ToolRetryPolicy,
    ToolUsage,
)

from core.tools.builtins._base import BuiltinToolBase
from core.tools.environments.workspace.manager import WorkspaceError, WorkspaceManager


class FilesystemMoveTool(BuiltinToolBase):
    identity = ToolIdentity(
        slug="filesystem.move", name="Filesystem Move",
        version="1.0.0", contract_version="1.0", publisher="dsrt", category="filesystem",
    )
    manifest = ToolManifest(
        identity=identity,
        description="Move or rename a file within the virtual workspace.",
        capabilities=[ToolCapabilityDeclaration(slug="filesystem.move")],
        permissions=ToolPermissionDeclaration(
            filesystem=ToolFilesystemPermission(read=True, write=True),
        ),
        risk_level=ToolRiskLevel.MEDIUM,
        side_effect=SideEffectClass.WRITE,
        limits=ToolLimits(timeout_seconds=10),
        retry=ToolRetryPolicy(allowed=False, max_attempts=1, idempotent=False),
        input_schema={
            "type": "object", "required": ["source", "destination"],
            "properties": {
                "source": {"type": "string"},
                "destination": {"type": "string"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {"source": {"type": "string"}, "destination": {"type": "string"}},
        },
    )

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        start_time = time.perf_counter()
        args = request.arguments or {}
        src = args.get("source", "")
        dst = args.get("destination", "")
        if not src or not dst:
            return self._error(request, start_time, "TOOL_INVALID_ARGUMENT", "Missing 'source' or 'destination'.")

        ws = WorkspaceManager()
        try:
            ws.move_file(src, dst, request.organization_id, request.execution_id)
        except WorkspaceError as e:
            return self._error(request, start_time, "TOOL_RUNTIME_FAILURE", str(e))

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        now = datetime.now(timezone.utc)
        return ToolExecutionResult(
            request_id=request.request_id, tool_execution_id=request.request_id,
            tool_slug=self.identity.slug, tool_version=self.identity.version,
            status=ToolExecutionStatus.COMPLETED,
            output={"source": src, "destination": dst},
            observations=[], artifact_ids=[], errors=[],
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