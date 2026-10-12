"""
EventSDK Implementation.

Wraps the Core ExecutionKernel to emit agent-scoped events into the trajectory.
"""

from __future__ import annotations

from typing import Any

from core.kernel.kernel import ExecutionKernel
from schemas.domain import EventType


class EventSDKImpl:
    """Concrete implementation of EventSDK."""

    def __init__(
        self,
        kernel: ExecutionKernel,
        execution_id: str,
        agent_slug: str,
    ) -> None:
        self._kernel = kernel
        self._execution_id = execution_id
        self._source = f"agent.{agent_slug}"

    async def emit(
        self, event_type: str, payload: dict[str, Any] | None = None,
    ) -> None:
        """Emit an agent-scoped event (always wrapped as AGENT_EVENT for taxonomy)."""
        merged_payload = {"agent_event_type": event_type, **(payload or {})}
        await self._kernel.emit_event(
            execution_id=self._execution_id,
            event_type=EventType.AGENT_EVENT,
            source=self._source,
            payload=merged_payload,
        )