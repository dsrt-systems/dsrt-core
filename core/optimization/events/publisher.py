"""
Event Publishing Infrastructure for C11 Optimization System.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Callable, Dict, List
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class OptimizationEvent(BaseModel):
    """Base class for optimization domain events."""

    event_type: str
    request_id: str
    tenant_id: str
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class OptimizationRequestedEvent(OptimizationEvent):
    event_type: str = "optimization.requested"


class OptimizationCompletedEvent(OptimizationEvent):
    event_type: str = "optimization.completed"
    plan_id: str
    estimated_cost_usd: float
    is_fallback: bool = False


class PolicyViolationEvent(OptimizationEvent):
    event_type: str = "optimization.policy_violation"
    violation_code: str
    message: str


class FallbackTriggeredEvent(OptimizationEvent):
    event_type: str = "optimization.fallback_triggered"
    reason: str


class ReconciliationCompletedEvent(OptimizationEvent):
    event_type: str = "optimization.reconciliation_completed"
    cost_error_pct: float
    latency_error_pct: float


class OptimizationEventPublisher:
    """In-memory event dispatcher for C11 system events."""

    _subscribers: Dict[str, List[Callable[[OptimizationEvent], None]]] = {}

    @classmethod
    def subscribe(
        cls, event_type: str, handler: Callable[[OptimizationEvent], None]
    ):
        if event_type not in cls._subscribers:
            cls._subscribers[event_type] = []
        cls._subscribers[event_type].append(handler)

    @classmethod
    def clear_subscribers(cls):
        cls._subscribers.clear()

    def publish(self, event: OptimizationEvent):
        """Dispatch event to registered handlers."""

        logger.info(
            f"Event published: [{event.event_type}] for request {event.request_id} (tenant={event.tenant_id})"
        )
        handlers = self._subscribers.get(event.event_type, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(
                    f"Error in event handler for {event.event_type}: {e}",
                    exc_info=True,
                )