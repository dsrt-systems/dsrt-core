"""
Resource Controller (C1 §33).

Tracks runtime resource consumption against configured limits.
Raises ResourceLimitError if limits are breached.
"""

from __future__ import annotations

from typing import Any

from core.api.errors.exceptions import ResourceLimitError
from core.observability.logging import get_logger
from schemas.domain import ResourceLimits


logger = get_logger("dsrt.kernel.resources")


class ResourceController:
    """Tracks and enforces resource limits for a single execution."""

    def __init__(self, execution_id: str, limits: ResourceLimits) -> None:
        self._execution_id = execution_id
        self._limits = limits

        self._model_calls = 0
        self._tool_calls = 0
        self._tokens = 0
        self._storage_mb = 0

    def track_model_call(self, tokens: int = 0) -> None:
        """Record a model call and check limits."""
        self._model_calls += 1
        if tokens > 0:
            self._tokens += tokens

        if self._limits.max_model_calls > 0 and self._model_calls > self._limits.max_model_calls:
            self._raise_limit("model_calls", self._model_calls, self._limits.max_model_calls)

        if self._limits.max_tokens and self._limits.max_tokens > 0 and self._tokens > self._limits.max_tokens:
            self._raise_limit("tokens", self._tokens, self._limits.max_tokens)

    def track_tool_call(self) -> None:
        """Record a tool call and check limits."""
        self._tool_calls += 1
        if self._limits.max_tool_calls > 0 and self._tool_calls > self._limits.max_tool_calls:
            self._raise_limit("tool_calls", self._tool_calls, self._limits.max_tool_calls)

    def get_usage(self) -> dict[str, Any]:
        """Return current tracked usage."""
        return {
            "model_calls": self._model_calls,
            "tool_calls": self._tool_calls,
            "tokens": self._tokens,
            "storage_mb": self._storage_mb,
        }

    def _raise_limit(self, resource: str, current: int, limit: int) -> None:
        logger.warning(
            "resource_limit_exceeded",
            execution_id=self._execution_id,
            resource=resource,
            current=current,
            limit=limit,
        )
        raise ResourceLimitError(
            f"Execution exceeded resource limit for {resource}.",
            metadata={
                "resource": resource,
                "current": current,
                "limit": limit,
            },
        )