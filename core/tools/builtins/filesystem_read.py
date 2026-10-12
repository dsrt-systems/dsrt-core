"""
filesystem.read — Read files from the virtual workspace (C3 §24).
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

from core.config import get_settings
from core.observability.logging import get_logger
from core.storage.identifiers import IdPrefix, new_id
from core.tools.builtins._base import BuiltinToolBase
from core.tools.environments.workspace.manager import WorkspaceError, WorkspaceManager


logger = get_logger("dsrt.tools.filesystem.read")


class FilesystemReadTool(BuiltinToolBase):
    identity = ToolIdentity(
        slug="filesystem.read",
        name="Filesystem Read",
        version="1.0.0",
        contract_version="1.0",
        publisher="dsrt",
        category="filesystem",
    )

    manifest = ToolManifest(
        identity=identity,
        description="Read a file from the virtual workspace.",
        capabilities=[
            ToolCapabilityDeclaration(slug="filesystem.read"),
        ],
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
                "path": {"type": "string", "description": "Virtual workspace path (e.g. /workspace/working/data.csv)"},
                "encoding": {"type": "string", "default": "utf-8"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "size_bytes": {"type": "integer"},
                "encoding": {"type": "string"},
            },
        },
    )

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        start_time = time.perf_counter()
        args = request.arguments or {}
        path = args.get("path", "")
        encoding = args.get("encoding", "utf-8")

        if not path:
            return self._error(request, start_time, "TOOL_INVALID_ARGUMENT", "Missing 'path'.")

        ws = WorkspaceManager()
        try:
            raw_bytes = ws.read_file(
                path, request.organization_id, request.execution_id,
            )
        except WorkspaceError as e:
            return self._error(request, start_time, "TOOL_RUNTIME_FAILURE", str(e))
        except Exception as e:
            return self._error(request, start_time, "TOOL_RUNTIME_FAILURE", str(e))

        try:
            content = raw_bytes.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            content = raw_bytes.decode("utf-8", errors="replace")

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        now = datetime.now(timezone.utc)

        output = {
            "path": path,
            "content": content,
            "size_bytes": len(raw_bytes),
            "encoding": encoding,
        }

        observation = ToolObservation(
            observation_id=new_id(IdPrefix.TOOL_OBSERVATION),
            observation_type=ObservationType.FILE_CONTENT,
            content=output,
            summary=f"Read {path} ({len(raw_bytes)} bytes)",
            source=self.identity.slug,
            timestamp=now,
            size_bytes=len(raw_bytes),
            provenance={
                "tool_slug": self.identity.slug,
                "execution_id": request.execution_id,
                "virtual_path": path,
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