"""
python.execute — Sandboxed Python Code Execution Tool (C3 §26-27).

Executes user-provided Python code in an isolated subprocess sandbox with
timeout, memory, and output limits enforced.

Security:
  - Fresh subprocess per execution (no shared state)
  - Hardened interpreter (-I -S)
  - Scrubbed environment variables
  - Workspace-only filesystem access
  - No network by default (controlled by sandbox policy)
  - Timeout and output caps enforced
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

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
from core.tools.environments.python_sandbox.sandbox import (
    PythonSandbox,
    PythonSandboxError,
)
from core.tools.environments.workspace.manager import WorkspaceManager


logger = get_logger("dsrt.tools.python_execute")


class PythonExecuteTool(BuiltinToolBase):
    """Execute Python code in a sandboxed subprocess."""

    identity = ToolIdentity(
        slug="python.execute",
        name="Python Execute",
        version="1.0.0",
        contract_version="1.0",
        publisher="dsrt",
        category="python",
    )

    manifest = ToolManifest(
        identity=identity,
        description=(
            "Execute Python code in an isolated subprocess sandbox. "
            "Code runs with hardened interpreter flags, scrubbed environment, "
            "wall-clock timeout, and output size caps. Capture return values "
            "by assigning them to a top-level variable named 'result'."
        ),
        capabilities=[
            ToolCapabilityDeclaration(slug="python.execute"),
            ToolCapabilityDeclaration(slug="code.compute"),
        ],
        permissions=ToolPermissionDeclaration(
            # Python sandbox has workspace filesystem access
            filesystem=ToolFilesystemPermission(read=True, write=True),
        ),
        risk_level=ToolRiskLevel.MEDIUM,
        side_effect=SideEffectClass.WRITE,
        limits=ToolLimits(
            timeout_seconds=120,
            max_output_bytes=5 * 1024 * 1024,
        ),
        retry=ToolRetryPolicy(
            allowed=False,  # Code execution is not auto-retryable
            max_attempts=1,
            idempotent=False,
        ),
        input_schema={
            "type": "object",
            "required": ["code"],
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute. Assign to 'result' to return a value.",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Override sandbox timeout (bounded by max).",
                },
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "exit_code": {"type": "integer"},
                "stdout": {"type": "string"},
                "stderr": {"type": "string"},
                "result": {},
                "duration_ms": {"type": "integer"},
                "timed_out": {"type": "boolean"},
                "output_truncated": {"type": "boolean"},
                "error_type": {"type": ["string", "null"]},
                "error_message": {"type": ["string", "null"]},
            },
        },
        tags=["code", "python", "sandbox"],
    )

    async def execute(
        self, request: ToolExecutionRequest,
    ) -> ToolExecutionResult:
        start_time = time.perf_counter()
        args = request.arguments or {}

        code = args.get("code")
        timeout_override = args.get("timeout_seconds")

        if not code or not isinstance(code, str):
            return self._error_result(
                request, start_time,
                "TOOL_INVALID_ARGUMENT",
                "Missing or invalid 'code' argument (must be non-empty string).",
            )

        if self._is_cancelled(request.request_id):
            return self._error_result(
                request, start_time,
                "TOOL_CANCELLED",
                "Request cancelled before execution.",
            )

        # Build sandbox with configured limits + workspace integration
        settings = get_settings()
        workspace_mgr = WorkspaceManager()

        # Try to use the execution's temp workspace as sandbox parent dir
        sandbox_parent = None
        try:
            if workspace_mgr.workspace_exists(
                request.organization_id, request.execution_id,
            ):
                real_ws = workspace_mgr._workspace_path(  # type: ignore[attr-defined]
                    request.organization_id, request.execution_id,
                )
                sandbox_parent = real_ws / "temp"
        except Exception:
            sandbox_parent = None

        sandbox = PythonSandbox(
            max_runtime_seconds=settings.python_sandbox_max_runtime_seconds,
            max_memory_mb=settings.python_sandbox_max_memory_mb,
            max_output_bytes=settings.python_sandbox_max_output_bytes,
            max_code_bytes=settings.python_sandbox_max_code_bytes,
            allow_network=settings.python_sandbox_allow_network,
            workspace_dir=sandbox_parent,
        )

        try:
            effective_timeout = (
                int(timeout_override) if timeout_override is not None else None
            )
            sandbox_result = await sandbox.execute(
                code, timeout_seconds=effective_timeout,
            )
        except PythonSandboxError as e:
            return self._error_result(
                request, start_time,
                "TOOL_SANDBOX_FAILURE",
                f"Sandbox setup failed: {e}",
            )
        except Exception as e:
            logger.exception("python_sandbox_unexpected_error")
            return self._error_result(
                request, start_time,
                "TOOL_RUNTIME_FAILURE",
                f"Unexpected sandbox error: {e}",
            )

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        now = datetime.now(timezone.utc)

        # Build observations
        observations: list[ToolObservation] = []

        # Observation 1: command output (stdout + stderr)
        command_summary_parts: list[str] = []
        if sandbox_result.stdout_bytes > 0:
            command_summary_parts.append(f"stdout: {sandbox_result.stdout_bytes} bytes")
        if sandbox_result.stderr_bytes > 0:
            command_summary_parts.append(f"stderr: {sandbox_result.stderr_bytes} bytes")
        if sandbox_result.timed_out:
            command_summary_parts.append("TIMED OUT")

        observations.append(
            ToolObservation(
                observation_id=new_id(IdPrefix.TOOL_OBSERVATION),
                observation_type=ObservationType.COMMAND_OUTPUT,
                content={
                    "stdout": sandbox_result.stdout,
                    "stderr": sandbox_result.stderr,
                    "exit_code": sandbox_result.exit_code,
                },
                summary=f"Python execution: {', '.join(command_summary_parts) or 'no output'}",
                source=self.identity.slug,
                timestamp=now,
                truncated=sandbox_result.output_truncated,
                size_bytes=sandbox_result.stdout_bytes + sandbox_result.stderr_bytes,
                provenance={
                    "tool_slug": self.identity.slug,
                    "tool_execution_id": request.request_id,
                    "execution_id": request.execution_id,
                },
            )
        )

        # Observation 2: result value (if any)
        if sandbox_result.result_value is not None:
            observations.append(
                ToolObservation(
                    observation_id=new_id(IdPrefix.TOOL_OBSERVATION),
                    observation_type=ObservationType.PYTHON_RESULT,
                    content={"result": sandbox_result.result_value},
                    summary=f"Python returned: {str(sandbox_result.result_value)[:200]}",
                    source=self.identity.slug,
                    timestamp=now,
                    provenance={
                        "tool_slug": self.identity.slug,
                        "tool_execution_id": request.request_id,
                        "execution_id": request.execution_id,
                    },
                )
            )

        # Build output payload
        output = {
            "success": sandbox_result.success,
            "exit_code": sandbox_result.exit_code,
            "stdout": sandbox_result.stdout,
            "stderr": sandbox_result.stderr,
            "result": sandbox_result.result_value,
            "duration_ms": sandbox_result.duration_ms,
            "timed_out": sandbox_result.timed_out,
            "output_truncated": sandbox_result.output_truncated,
            "error_type": sandbox_result.error_type,
            "error_message": sandbox_result.error_message,
        }

        # Determine final status + errors
        if sandbox_result.timed_out:
            status = ToolExecutionStatus.FAILED
            errors = [
                ToolExecutionError(
                    code="TOOL_TIMEOUT",
                    message=sandbox_result.error_message or "Execution timed out.",
                    retryable=False,
                )
            ]
        elif not sandbox_result.success:
            status = ToolExecutionStatus.FAILED
            errors = [
                ToolExecutionError(
                    code="TOOL_SANDBOX_FAILURE",
                    message=(
                        sandbox_result.error_message
                        or f"Python exited with code {sandbox_result.exit_code}."
                    ),
                    retryable=False,
                    metadata={
                        "error_type": sandbox_result.error_type,
                        "exit_code": sandbox_result.exit_code,
                    },
                )
            ]
        else:
            status = ToolExecutionStatus.COMPLETED
            errors = []

        logger.info(
            "python_execute_completed",
            success=sandbox_result.success,
            exit_code=sandbox_result.exit_code,
            duration_ms=duration_ms,
            timed_out=sandbox_result.timed_out,
            output_truncated=sandbox_result.output_truncated,
        )

        return ToolExecutionResult(
            request_id=request.request_id,
            tool_execution_id=request.request_id,
            tool_slug=self.identity.slug,
            tool_version=self.identity.version,
            status=status,
            output=output,
            observations=observations,
            artifact_ids=[],
            errors=errors,
            usage=ToolUsage(duration_ms=duration_ms),
            duration_ms=duration_ms,
            attempt=request.attempt,
            started_at=now,
            completed_at=now,
        )

    def _error_result(
        self,
        request: ToolExecutionRequest,
        start_time: float,
        error_code: str,
        error_message: str,
        *,
        retryable: bool = False,
    ) -> ToolExecutionResult:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolExecutionResult(
            request_id=request.request_id,
            tool_execution_id=request.request_id,
            tool_slug=self.identity.slug,
            tool_version=self.identity.version,
            status=ToolExecutionStatus.FAILED,
            output=None,
            observations=[],
            artifact_ids=[],
            errors=[
                ToolExecutionError(
                    code=error_code,
                    message=error_message,
                    retryable=retryable,
                )
            ],
            usage=ToolUsage(duration_ms=duration_ms),
            duration_ms=duration_ms,
            attempt=request.attempt,
        )