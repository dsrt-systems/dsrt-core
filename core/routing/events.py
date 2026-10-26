# core/routing/events.py
"""
C9 Routing Events (§48).

All routing lifecycle events.  These become part of the execution
trajectory and are emitted at each stage of the routing pipeline.

Events are lightweight frozen dataclasses — the event bus /
observability layer (C2) handles persistence and distribution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class RoutingEventType(str, Enum):
    """All C9 routing event types (§48)."""

    ROUTING_STARTED = "ROUTING_STARTED"
    REQUIREMENTS_EXTRACTED = "REQUIREMENTS_EXTRACTED"
    CANDIDATES_GENERATED = "CANDIDATES_GENERATED"
    CANDIDATE_REJECTED = "CANDIDATE_REJECTED"
    ROUTE_EVALUATED = "ROUTE_EVALUATED"
    ROUTE_SELECTED = "ROUTE_SELECTED"
    ROUTE_STARTED = "ROUTE_STARTED"
    ROUTE_CHANGED = "ROUTE_CHANGED"
    FALLBACK_TRIGGERED = "FALLBACK_TRIGGERED"
    MODEL_SWITCHED = "MODEL_SWITCHED"
    AGENT_SWITCHED = "AGENT_SWITCHED"
    ROUTING_COMPLETED = "ROUTING_COMPLETED"
    ROUTING_FAILED = "ROUTING_FAILED"


@dataclass(frozen=True)
class RoutingEvent:
    """A single routing lifecycle event.

    Attributes:
        event_type: The event category.
        task_id: The task being routed.
        decision_id: The routing decision ID (if available).
        payload: Event-specific data (model IDs, reasons, etc.).
        timestamp: When the event occurred.
    """

    event_type: RoutingEventType
    task_id: str
    decision_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class RoutingEventEmitter:
    """Collects and emits routing events (§48).

    In production this would feed into the C2 observability bus.
    For C9, it provides an in-memory event log that can be
    inspected for testing and auditability.

    Args:
        listeners: Optional list of callables invoked on each event.
    """

    def __init__(
        self,
        listeners: list[Any] | None = None,
    ) -> None:
        self._events: list[RoutingEvent] = []
        self._listeners: list[Any] = listeners or []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def emit(
        self,
        event_type: RoutingEventType,
        task_id: str,
        decision_id: str | None = None,
        **payload: Any,
    ) -> RoutingEvent:
        """Emit a routing event.

        Args:
            event_type: The event type.
            task_id: Task identifier.
            decision_id: Routing decision identifier.
            **payload: Event-specific data.

        Returns:
            The created ``RoutingEvent``.
        """
        event = RoutingEvent(
            event_type=event_type,
            task_id=task_id,
            decision_id=decision_id,
            payload=payload,
        )
        self._events.append(event)

        for listener in self._listeners:
            try:
                listener(event)
            except Exception:
                pass  # listeners must not break the pipeline

        return event

    # Convenience emitters for each event type

    def routing_started(self, task_id: str, **kw: Any) -> RoutingEvent:
        return self.emit(RoutingEventType.ROUTING_STARTED, task_id, **kw)

    def requirements_extracted(
        self, task_id: str, **kw: Any,
    ) -> RoutingEvent:
        return self.emit(
            RoutingEventType.REQUIREMENTS_EXTRACTED, task_id, **kw,
        )

    def candidates_generated(
        self, task_id: str, decision_id: str, count: int, **kw: Any,
    ) -> RoutingEvent:
        return self.emit(
            RoutingEventType.CANDIDATES_GENERATED,
            task_id, decision_id, count=count, **kw,
        )

    def candidate_rejected(
        self,
        task_id: str,
        decision_id: str,
        candidate_id: str,
        reason: str,
        **kw: Any,
    ) -> RoutingEvent:
        return self.emit(
            RoutingEventType.CANDIDATE_REJECTED,
            task_id, decision_id,
            candidate_id=candidate_id, reason=reason, **kw,
        )

    def route_evaluated(
        self, task_id: str, decision_id: str, **kw: Any,
    ) -> RoutingEvent:
        return self.emit(
            RoutingEventType.ROUTE_EVALUATED, task_id, decision_id, **kw,
        )

    def route_selected(
        self,
        task_id: str,
        decision_id: str,
        model_id: str,
        **kw: Any,
    ) -> RoutingEvent:
        return self.emit(
            RoutingEventType.ROUTE_SELECTED,
            task_id, decision_id, model_id=model_id, **kw,
        )

    def route_started(
        self, task_id: str, decision_id: str, **kw: Any,
    ) -> RoutingEvent:
        return self.emit(
            RoutingEventType.ROUTE_STARTED, task_id, decision_id, **kw,
        )

    def route_changed(
        self,
        task_id: str,
        decision_id: str,
        from_model: str,
        to_model: str,
        reason: str,
        **kw: Any,
    ) -> RoutingEvent:
        return self.emit(
            RoutingEventType.ROUTE_CHANGED,
            task_id, decision_id,
            from_model=from_model, to_model=to_model,
            reason=reason, **kw,
        )

    def fallback_triggered(
        self,
        task_id: str,
        decision_id: str,
        trigger: str,
        **kw: Any,
    ) -> RoutingEvent:
        return self.emit(
            RoutingEventType.FALLBACK_TRIGGERED,
            task_id, decision_id, trigger=trigger, **kw,
        )

    def model_switched(
        self,
        task_id: str,
        decision_id: str,
        from_model: str,
        to_model: str,
        **kw: Any,
    ) -> RoutingEvent:
        return self.emit(
            RoutingEventType.MODEL_SWITCHED,
            task_id, decision_id,
            from_model=from_model, to_model=to_model, **kw,
        )

    def agent_switched(
        self,
        task_id: str,
        decision_id: str,
        from_agent: str,
        to_agent: str,
        **kw: Any,
    ) -> RoutingEvent:
        return self.emit(
            RoutingEventType.AGENT_SWITCHED,
            task_id, decision_id,
            from_agent=from_agent, to_agent=to_agent, **kw,
        )

    def routing_completed(
        self, task_id: str, decision_id: str, **kw: Any,
    ) -> RoutingEvent:
        return self.emit(
            RoutingEventType.ROUTING_COMPLETED, task_id, decision_id, **kw,
        )

    def routing_failed(
        self, task_id: str, decision_id: str | None, reason: str, **kw: Any,
    ) -> RoutingEvent:
        return self.emit(
            RoutingEventType.ROUTING_FAILED,
            task_id, decision_id, reason=reason, **kw,
        )

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    @property
    def events(self) -> list[RoutingEvent]:
        """All emitted events in chronological order."""
        return list(self._events)

    def events_for_task(self, task_id: str) -> list[RoutingEvent]:
        """All events for a specific task."""
        return [e for e in self._events if e.task_id == task_id]

    def events_of_type(
        self, event_type: RoutingEventType,
    ) -> list[RoutingEvent]:
        """All events of a specific type."""
        return [e for e in self._events if e.event_type == event_type]

    def clear(self) -> int:
        """Clear all events. Returns count cleared."""
        count = len(self._events)
        self._events.clear()
        return count