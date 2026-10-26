# Path: core/execution/observability/events.py
"""
C10 Event Integration & Publisher System.
Defines standard lifecycle events and handles outbox buffering and dispatching.
"""

import uuid
import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field
from core.execution.observability.traces import Redactor


class C10EventType(str, Enum):
    """Standard lifecycle events for executions and comparative experiments."""

    # Execution lifecycle events
    EXECUTION_CREATED = "execution.created"
    EXECUTION_VALIDATING = "execution.validating"
    EXECUTION_PREPARING = "execution.preparing"
    EXECUTION_STARTED = "execution.started"
    EXECUTION_STEP_STARTED = "execution.step.started"
    EXECUTION_STEP_COMPLETED = "execution.step.completed"
    EXECUTION_MODEL_INVOKED = "execution.model.invoked"
    EXECUTION_MODEL_COMPLETED = "execution.model.completed"
    EXECUTION_TOOL_INVOKED = "execution.tool.invoked"
    EXECUTION_TOOL_COMPLETED = "execution.tool.completed"
    EXECUTION_VERIFICATION_STARTED = "execution.verification.started"
    EXECUTION_VERIFICATION_COMPLETED = "execution.verification.completed"
    EXECUTION_REPAIR_STARTED = "execution.repair.started"
    EXECUTION_REPAIR_COMPLETED = "execution.repair.completed"
    EXECUTION_BUDGET_WARNING = "execution.budget.warning"
    EXECUTION_CANCELLED = "execution.cancelled"
    EXECUTION_FAILED = "execution.failed"
    EXECUTION_COMPLETED = "execution.completed"

    # Experiment lifecycle events
    EXPERIMENT_CREATED = "experiment.created"
    EXPERIMENT_STARTED = "experiment.started"
    EXPERIMENT_RUN_STARTED = "experiment.run.started"
    EXPERIMENT_RUN_COMPLETED = "experiment.run.completed"
    EXPERIMENT_EVALUATION_COMPLETED = "experiment.evaluation.completed"
    EXPERIMENT_COMPARISON_COMPLETED = "experiment.comparison.completed"


class ExecutionEvent(BaseModel):
    """Structured event model for audit trails and real-time streaming."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: C10EventType
    workspace_id: str
    execution_id: Optional[str] = None
    experiment_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    version: str = "1.0"


class EventPublisher:
    """In-memory event publisher with subscriber callbacks and outbox buffering."""

    def __init__(self):
        self._subscribers: Dict[str, List[Callable[[ExecutionEvent], None]]] = {}
        self._outbox: List[ExecutionEvent] = []

    def subscribe(self, event_type: str, handler: Callable[[ExecutionEvent], None]) -> None:
        """Subscribes a callback handler to a specific event type or wildcard '*'."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def publish(
        self,
        event_type: C10EventType,
        workspace_id: str,
        execution_id: Optional[str] = None,
        experiment_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> ExecutionEvent:
        """Constructs, redacts, buffers, and dispatches an execution event."""
        sanitized_payload = Redactor.redact_data(payload or {})
        event = ExecutionEvent(
            event_type=event_type,
            workspace_id=workspace_id,
            execution_id=execution_id,
            experiment_id=experiment_id,
            payload=sanitized_payload,
        )

        # Buffer into durable outbox
        self._outbox.append(event)

        # Notify direct subscribers
        handlers = self._subscribers.get(event_type.value, []) + self._subscribers.get("*", [])
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                # Log or isolate handler failure to preserve main execution flow
                pass

        return event

    def get_outbox(self) -> List[ExecutionEvent]:
        """Returns buffered events."""
        return list(self._outbox)

    def clear_outbox(self) -> None:
        """Clears the buffered event outbox."""
        self._outbox.clear()