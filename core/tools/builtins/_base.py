"""
Base class for built-in DSRT Tools.

Provides shared lifecycle management for simple built-in tools.
Tools are stateless w.r.t. previous executions.
"""

from __future__ import annotations

import asyncio
from typing import Any

from schemas.domain.tool import (
    ToolContext,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolHealth,
    ToolIdentity,
    ToolInitializationResult,
    ToolManifest,
)
from schemas.domain.enums import ToolHealthStatus


class BuiltinToolBase:
    """Shared implementation surface for built-in tools."""

    identity: ToolIdentity
    manifest: ToolManifest

    def __init__(self) -> None:
        self._context: ToolContext | None = None
        self._cancelled: set[str] = set()
        self._lock = asyncio.Lock()

    async def initialize(
        self, context: ToolContext,
    ) -> ToolInitializationResult:
        """Prepare the tool for execution. Default implementation accepts the context."""
        self._context = context
        return ToolInitializationResult(ready=True, message="Ready.")

    async def execute(
        self, request: ToolExecutionRequest,
    ) -> ToolExecutionResult:
        """Must be implemented by subclasses."""
        raise NotImplementedError

    async def cancel(self, request_id: str) -> None:
        """Mark a specific request as cancelled."""
        async with self._lock:
            self._cancelled.add(request_id)

    async def health(self) -> ToolHealth:
        """Default health: HEALTHY unless subclass overrides."""
        return ToolHealth(
            tool_slug=self.identity.slug,
            tool_version=self.identity.version,
            status=ToolHealthStatus.HEALTHY,
        )

    def _is_cancelled(self, request_id: str) -> bool:
        return request_id in self._cancelled