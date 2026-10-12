"""
DSRT Tool Fabric Error Taxonomy (C3 §46).

All tool-related errors flow through this hierarchy. Tool implementations
raise ToolRuntimeError (or subclass); the Execution Engine normalizes
anything else to TOOL_RUNTIME_FAILURE.

Note: `ToolFabricError` is deliberately named to avoid collision with:
  - `schemas.domain.model_fabric.ToolError` (C2 — a model's request to call a tool)
  - `schemas.domain.tool.ToolExecutionError`  (C3 — error data inside a result)

The three concepts are:
  * ModelFabric.ToolError  → a tool-call payload emitted by a model.
  * Tool.ToolExecutionError → a serializable error record inside a result.
  * ToolFabricError         → an exception raised at runtime inside Core.
"""

from __future__ import annotations

from typing import Any

from core.api.errors.exceptions import DSRTError
from schemas.domain.enums import ErrorCode


class ToolFabricError(DSRTError):
    """Base for every Tool Fabric error surfaced to Core."""

    error_code = ErrorCode.TOOL_RUNTIME_FAILURE
    http_status = 500


class ToolNotFoundError(ToolFabricError):
    error_code = ErrorCode.TOOL_NOT_FOUND
    http_status = 404


class ToolVersionUnavailableError(ToolFabricError):
    error_code = ErrorCode.TOOL_VERSION_UNAVAILABLE
    http_status = 404


class ToolPermissionDeniedError(ToolFabricError):
    error_code = ErrorCode.TOOL_PERMISSION_DENIED
    http_status = 403


class ToolPolicyDeniedError(ToolFabricError):
    error_code = ErrorCode.TOOL_POLICY_DENIED
    http_status = 403


class ToolTimeoutError(ToolFabricError):
    error_code = ErrorCode.TOOL_TIMEOUT
    http_status = 504


class ToolRateLimitedError(ToolFabricError):
    error_code = ErrorCode.TOOL_RATE_LIMITED
    http_status = 429


class ToolInvalidArgumentError(ToolFabricError):
    error_code = ErrorCode.TOOL_INVALID_ARGUMENT
    http_status = 400


class ToolRuntimeError(ToolFabricError):
    """Raised by tool implementations for recoverable runtime failures."""

    error_code = ErrorCode.TOOL_RUNTIME_FAILURE
    http_status = 500


class ToolNetworkFailureError(ToolFabricError):
    error_code = ErrorCode.TOOL_NETWORK_FAILURE
    http_status = 502


class ToolSandboxFailureError(ToolFabricError):
    error_code = ErrorCode.TOOL_SANDBOX_FAILURE
    http_status = 500


class ToolResourceLimitError(ToolFabricError):
    error_code = ErrorCode.TOOL_RESOURCE_LIMIT
    http_status = 429


class ToolCredentialFailureError(ToolFabricError):
    error_code = ErrorCode.TOOL_CREDENTIAL_FAILURE
    http_status = 500


class ToolOutputTooLargeError(ToolFabricError):
    error_code = ErrorCode.TOOL_OUTPUT_TOO_LARGE
    http_status = 413


class ToolCancelledError(ToolFabricError):
    error_code = ErrorCode.TOOL_CANCELLED
    http_status = 499


class ToolApprovalRequiredError(ToolFabricError):
    """Raised when a tool invocation requires explicit human approval."""

    error_code = ErrorCode.TOOL_APPROVAL_REQUIRED
    http_status = 202  # Accepted — pending approval.

    def __init__(
        self,
        message: str,
        *,
        approval_request_id: str,
        metadata: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ) -> None:
        meta = dict(metadata or {})
        meta["approval_request_id"] = approval_request_id
        super().__init__(message, metadata=meta, cause=cause)
        self.approval_request_id = approval_request_id


class ToolApprovalRejectedError(ToolFabricError):
    error_code = ErrorCode.TOOL_APPROVAL_REJECTED
    http_status = 403


class ToolApprovalExpiredError(ToolFabricError):
    error_code = ErrorCode.TOOL_APPROVAL_EXPIRED
    http_status = 408


class EnvironmentFabricError(DSRTError):
    """Base for environment-related errors."""

    error_code = ErrorCode.ENVIRONMENT_UNAVAILABLE
    http_status = 500


class EnvironmentNotFoundError(EnvironmentFabricError):
    error_code = ErrorCode.ENVIRONMENT_NOT_FOUND
    http_status = 404


class EnvironmentProvisionFailedError(EnvironmentFabricError):
    error_code = ErrorCode.ENVIRONMENT_PROVISION_FAILED
    http_status = 500


class EnvironmentResourceExhaustedError(EnvironmentFabricError):
    error_code = ErrorCode.ENVIRONMENT_RESOURCE_EXHAUSTED
    http_status = 429


class WorldFabricError(DSRTError):
    """Base for world-related errors."""

    error_code = ErrorCode.WORLD_UNAVAILABLE
    http_status = 500


class WorldNotFoundError(WorldFabricError):
    error_code = ErrorCode.WORLD_NOT_FOUND
    http_status = 404


class WorldProvisionFailedError(WorldFabricError):
    error_code = ErrorCode.WORLD_PROVISION_FAILED
    http_status = 500