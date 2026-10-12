"""
Execution Cancellation Manager (C1 §34).

Maintains a registry of cancellation tokens (asyncio.Event) for active executions.
Allows the API to broadcast a cancellation signal to the running AgentAdapter,
ToolRuntime, and ModelGateway.
"""

from __future__ import annotations

import asyncio

from core.observability.logging import get_logger


logger = get_logger("dsrt.kernel.cancellation")


class CancellationManager:
    """Manages cancellation tokens for active executions."""

    def __init__(self) -> None:
        # Maps execution_id -> asyncio.Event
        self._tokens: dict[str, asyncio.Event] = {}

    def register(self, execution_id: str) -> asyncio.Event:
        """Create and register a new cancellation token for an execution."""
        if execution_id not in self._tokens:
            self._tokens[execution_id] = asyncio.Event()
        return self._tokens[execution_id]

    def unregister(self, execution_id: str) -> None:
        """Remove a token when execution completes naturally or fails."""
        self._tokens.pop(execution_id, None)

    def cancel(self, execution_id: str) -> bool:
        """Trigger the cancellation signal. Returns True if a token was active."""
        event = self._tokens.get(execution_id)
        if event is not None:
            event.set()
            logger.info("cancellation_signal_broadcast", execution_id=execution_id)
            return True
        return False

    def get_token(self, execution_id: str) -> asyncio.Event | None:
        """Retrieve an active token, if any."""
        return self._tokens.get(execution_id)


# Global cancellation manager instance
cancellation_manager = CancellationManager()