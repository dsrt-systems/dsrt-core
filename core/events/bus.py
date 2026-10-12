"""
DSRT Event Bus & Execution Context Tracing.

Provides async in-memory event publishing/subscribing alongside contextvar-based
correlation tracking for execution_id, task_id, and request_id.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from typing import Any, Callable, Coroutine

from core.observability.logging import get_logger
from schemas.domain import ExecutionEvent


logger = get_logger("dsrt.events.bus")

# Contextvars for automatic context injection into loggers and events
ctx_execution_id: ContextVar[str | None] = ContextVar("ctx_execution_id", default=None)
ctx_task_id: ContextVar[str | None] = ContextVar("ctx_task_id", default=None)
ctx_request_id: ContextVar[str | None] = ContextVar("ctx_request_id", default=None)

EventHandler = Callable[[ExecutionEvent], Coroutine[Any, Any, None]]


class EventBus:
    """Async event bus for in-process event fan-out."""

    def __init__(self) -> None:
        self._subscribers: list[EventHandler] = []

    def subscribe(self, handler: EventHandler) -> None:
        """Register an async event subscriber."""
        if handler not in self._subscribers:
            self._subscribers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        """Remove a subscriber."""
        if handler in self._subscribers:
            self._subscribers.remove(handler)

    async def publish(self, event: ExecutionEvent) -> None:
        """Publish an event to all subscribers without blocking execution on errors."""
        if not self._subscribers:
            return

        tasks = []
        for handler in self._subscribers:
            tasks.append(self._safe_call(handler, event))

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_call(self, handler: EventHandler, event: ExecutionEvent) -> None:
        try:
            await handler(event)
        except Exception as e:
            logger.error(
                "event_subscriber_error",
                subscriber=handler.__name__,
                event_type=event.event_type,
                error=str(e),
            )


# Global event bus instance
event_bus = EventBus()