"""
filesystem.promote_to_artifact — Promote a workspace file to a durable Artifact (C3 §43).
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

from core.kernel.fingerprint import content_hash
from core.observability.logging import get_logger
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models import Artifact
from core.tools.builtins._base import BuiltinToolBase
from core.tools.environments.workspace.manager import WorkspaceError, WorkspaceManager


logger = get_logger("dsrt.tools.filesystem.promote")


class FilesystemPromoteToArtifactTool(BuiltinToolBase):
    identity = ToolIdentity(
        slug="filesystem.promote_to_artifact",
        name="Promote to Artifact",
        version="1.0.0", contract_version="1.0", publisher="dsrt", category="filesystem",
    )
    manifest = ToolManifest(
        identity=identity,
        description=(
            "Promote a file from the virtual workspace to a durable DSRT Artifact. "
            "The file content is read from the workspace and stored as an Artifact "
            "linked to the current execution."
        ),
        capabilities=[ToolCapabilityDeclaration(slug="filesystem.promote_to_artifact")],
        permissions=ToolPermissionDeclaration(
            filesystem=ToolFilesystemPermission(read=True),
        ),
        risk_level=ToolRiskLevel.MEDIUM,
        side_effect=SideEffectClass.WRITE,
        limits=ToolLimits(timeout_seconds=30),
        retry=ToolRetryPolicy(allowed=True, max_attempts=2, idempotent=True),
        input_schema={
            "type": "object", "required": ["path", "name", "artifact_type"],
            "properties": {
                "path": {"type": "string"},
                "name": {"type": "string"},
                "artifact_type": {"type": "string"},
                "mime_type": {"type": "string", "default": "application/octet-stream"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "artifact_id": {"type": "string"},
                "name": {"type": "string"},
                "size_bytes": {"type": "integer"},
            },
        },
    )

    def __init__(self) -> None:
        super().__init__()
        self._session = None  # Set by the execution engine if available

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        start_time = time.perf_counter()
        args = request.arguments or {}
        path = args.get("path", "")
        name = args.get("name", "")
        artifact_type = args.get("artifact_type", "DOCUMENT")
        mime_type = args.get("mime_type", "application/octet-stream")

        if not path or not name:
            return self._error(
                request, start_time, "TOOL_INVALID_ARGUMENT",
                "Missing 'path' and/or 'name'.",
            )

        ws = WorkspaceManager()
        try:
            raw_bytes = ws.read_file(
                path, request.organization_id, request.execution_id,
            )
        except WorkspaceError as e:
            return self._error(request, start_time, "TOOL_RUNTIME_FAILURE", str(e))

        # Create artifact inline (same pattern as ArtifactSDKImpl)
        artifact_id = new_id(IdPrefix.ARTIFACT)
        hash_hex = content_hash(raw_bytes)
        storage_ref = f"inline://{artifact_id}"

        # Note: In a full implementation, this would use the ArtifactSDK or
        # a repository. For C3.8, we return the artifact metadata and let
        # the execution engine handle persistence.
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        now = datetime.now(timezone.utc)

        output = {
            "artifact_id": artifact_id,
            "name": name,
            "artifact_type": artifact_type,
            "mime_type": mime_type,
            "size_bytes": len(raw_bytes),
            "content_hash": hash_hex,
            "storage_reference": storage_ref,
        }

        logger.info(
            "file_promoted_to_artifact",
            artifact_id=artifact_id,
            name=name,
            size_bytes=len(raw_bytes),
            virtual_path=path,
        )

        return ToolExecutionResult(
            request_id=request.request_id,
            tool_execution_id=request.request_id,
            tool_slug=self.identity.slug,
            tool_version=self.identity.version,
            status=ToolExecutionStatus.COMPLETED,
            output=output,
            observations=[],
            artifact_ids=[artifact_id],
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
            request_id=request.request_id, tool_execution_id=request.request_id,
            tool_slug=self.identity.slug, tool_version=self.identity.version,
            status=ToolExecutionStatus.FAILED,
            output=None, observations=[], artifact_ids=[],
            errors=[ToolExecutionError(code=code, message=msg)],
            usage=ToolUsage(duration_ms=duration_ms),
            duration_ms=duration_ms, attempt=request.attempt,
        )