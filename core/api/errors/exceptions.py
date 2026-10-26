"""
DSRT Core Error Taxonomy — C1 §35.

Every error surfaced to a client passes through this hierarchy.
Provider-specific errors are attached as diagnostic metadata, never leaked as
the primary error type.
"""

from __future__ import annotations

from typing import Any

from schemas.domain.enums import ErrorCode


class DSRTError(Exception):
    """Base for every DSRT-normalized error."""

    error_code: ErrorCode = ErrorCode.INTERNAL_ERROR
    http_status: int = 500

    def __init__(
        self,
        message: str,
        *,
        metadata: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.metadata = metadata or {}
        self.cause = cause

    def to_response(self) -> dict[str, Any]:
        """Serialize into the wire error envelope."""
        return {
            "error": {
                "code": self.error_code.value,
                "message": self.message,
                "metadata": self.metadata,
            }
        }


# --- Auth / authorization ---

class AuthenticationError(DSRTError):
    error_code = ErrorCode.AUTHENTICATION_FAILED
    http_status = 401


class AuthorizationError(DSRTError):
    error_code = ErrorCode.AUTHORIZATION_DENIED
    http_status = 403


# --- Validation ---

class ValidationError(DSRTError):
    error_code = ErrorCode.VALIDATION_ERROR
    http_status = 400


class NotFoundError(DSRTError):
    error_code = ErrorCode.VALIDATION_ERROR
    http_status = 404


class ConflictError(DSRTError):
    error_code = ErrorCode.VALIDATION_ERROR
    http_status = 409


# --- Resource / execution (used later in C1.6+) ---

class ResourceLimitError(DSRTError):
    error_code = ErrorCode.RESOURCE_LIMIT_EXCEEDED
    http_status = 429


class AgentNotFoundError(DSRTError):
    error_code = ErrorCode.AGENT_NOT_FOUND
    http_status = 404


# Alias used by orchestration router
ForbiddenError = AuthorizationError
