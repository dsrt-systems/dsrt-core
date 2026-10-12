"""
Execution and Task Lifecycle State Machines (C1 §28-29).

Enforces valid, deterministic state transitions.
Invalid state transitions raise ValidationError.
"""

from __future__ import annotations

from core.api.errors.exceptions import ValidationError
from schemas.domain.enums import ExecutionStatus, TaskStatus


# Valid transitions for Task lifecycle:
# CREATED -> QUEUED -> EXECUTING -> COMPLETED / FAILED / CANCELLED
_VALID_TASK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.CREATED: {TaskStatus.QUEUED, TaskStatus.CANCELLED},
    TaskStatus.QUEUED: {TaskStatus.EXECUTING, TaskStatus.CANCELLED},
    TaskStatus.EXECUTING: {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: {TaskStatus.QUEUED},  # retry
    TaskStatus.CANCELLED: set(),
}

# Valid transitions for Execution lifecycle (C1 §29):
# QUEUED -> INITIALIZING -> RUNNING -> VERIFYING -> FINALIZING -> COMPLETED
# Any active state -> CANCELLING -> CANCELLED or FAILED
_VALID_EXECUTION_TRANSITIONS: dict[ExecutionStatus, set[ExecutionStatus]] = {
    ExecutionStatus.QUEUED: {
        ExecutionStatus.INITIALIZING,
        ExecutionStatus.CANCELLING,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.FAILED,
    },
    ExecutionStatus.INITIALIZING: {
        ExecutionStatus.RUNNING,
        ExecutionStatus.CANCELLING,
        ExecutionStatus.FAILED,
    },
    ExecutionStatus.RUNNING: {
        ExecutionStatus.VERIFYING,
        ExecutionStatus.FINALIZING,
        ExecutionStatus.CANCELLING,
        ExecutionStatus.FAILED,
    },
    ExecutionStatus.VERIFYING: {
        ExecutionStatus.FINALIZING,
        ExecutionStatus.CANCELLING,
        ExecutionStatus.FAILED,
    },
    ExecutionStatus.FINALIZING: {
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
    },
    ExecutionStatus.COMPLETED: set(),
    ExecutionStatus.FAILED: set(),
    ExecutionStatus.CANCELLING: {ExecutionStatus.CANCELLED, ExecutionStatus.FAILED},
    ExecutionStatus.CANCELLED: set(),
}


def validate_task_transition(current: TaskStatus, target: TaskStatus) -> None:
    """Validate task lifecycle transition."""
    if current == target:
        return
    allowed = _VALID_TASK_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValidationError(
            f"Invalid task state transition from {current.value} to {target.value}.",
            metadata={"current_status": current.value, "target_status": target.value},
        )


def validate_execution_transition(
    current: ExecutionStatus, target: ExecutionStatus,
) -> None:
    """Validate execution lifecycle transition."""
    if current == target:
        return
    allowed = _VALID_EXECUTION_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValidationError(
            f"Invalid execution state transition from {current.value} to {target.value}.",
            metadata={
                "current_status": current.value,
                "target_status": target.value,
            },
        )