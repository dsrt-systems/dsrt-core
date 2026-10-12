"""
ToolRuntime SDK Contract (C1 §20-21).

Agents request tool capabilities; Core handles authorization, execution,
timeouts, retries, security, and result normalization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SDKToolResult:
    """Canonical tool execution result."""

    tool_slug: str
    status: str  # "SUCCESS" | "FAILED" | "TIMEOUT" | "DENIED"
    output: Any
    duration_ms: int = 0
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolSDK(Protocol):
    """Tool Runtime SDK — the action capability."""

    async def call(
        self, tool_slug: str, arguments: dict[str, Any],
    ) -> SDKToolResult:
        """Invoke a tool via Core's authorized runtime."""
        ...

    async def available_tools(self) -> list[str]:
        """List tool slugs available to this agent under current policy."""
        ...