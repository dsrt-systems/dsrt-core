"""
Tool Execution Lifecycle State Machine (C3 §16).

Deterministic, validated state transitions for tool executions.
Mirrors the C1 Execution lifecycle pattern but scoped to individual tool calls.
"""

from __future__ import annotations

from schemas.domain.enums import ToolExecutionStatus

from core.api.errors.exceptions import ValidationError


_VALID_TRANSITIONS: dict[ToolExecutionStatus, set[ToolExecutionStatus]] = {
    ToolExecutionStatus.REQUESTED: {
        ToolExecutionStatus.AUTHORIZING,
        ToolExecutionStatus.CANCELLED,
    },
    ToolExecutionStatus.AUTHORIZING: {
        ToolExecutionStatus.AUTHORIZED,
        ToolExecutionStatus.APPROVAL_REQUIRED,
        ToolExecutionStatus.FAILED,
        ToolExecutionStatus.CANCELLED,
    },
    ToolExecutionStatus.AUTHORIZED: {
        ToolExecutionStatus.QUEUED,
        ToolExecutionStatus.FAILED,
        ToolExecutionStatus.CANCELLED,
    },
    ToolExecutionStatus.APPROVAL_REQUIRED: {
        ToolExecutionStatus.QUEUED,       # After approval granted
        ToolExecutionStatus.CANCELLED,     # Approval denied or expired
        ToolExecutionStatus.FAILED,
    },
    ToolExecutionStatus.QUEUED: {
        ToolExecutionStatus.STARTED,
        ToolExecutionStatus.CANCELLED,
    },
    ToolExecutionStatus.STARTED: {
        ToolExecutionStatus.RUNNING,
        ToolExecutionStatus.FAILED,
        ToolExecutionStatus.CANCELLING,
    },
    ToolExecutionStatus.RUNNING: {
        ToolExecutionStatus.OBSERVING,
        ToolExecutionStatus.FAILED,
        ToolExecutionStatus.CANCELLING,
    },
    ToolExecutionStatus.OBSERVING: {
        ToolExecutionStatus.COMPLETED,
        ToolExecutionStatus.FAILED,
        ToolExecutionStatus.CANCELLING,
    },
    ToolExecutionStatus.COMPLETED: set(),  # Terminal
    ToolExecutionStatus.FAILED: set(),     # Terminal
    ToolExecutionStatus.CANCELLING: {
        ToolExecutionStatus.CANCELLED,
        ToolExecutionStatus.FAILED,
    },
    ToolExecutionStatus.CANCELLED: set(),  # Terminal
}

# Shortcut transitions for simple tools that skip intermediate states
_SHORTCUT_TRANSITIONS: dict[ToolExecutionStatus, set[ToolExecutionStatus]] = {
    ToolExecutionStatus.REQUESTED: {
        ToolExecutionStatus.AUTHORIZED,    # Skip AUTHORIZING if no approval needed
    },
    ToolExecutionStatus.AUTHORIZED: {
        ToolExecutionStatus.STARTED,       # Skip QUEUED for synchronous execution
    },
    ToolExecutionStatus.STARTED: {
        ToolExecutionStatus.OBSERVING,     # Skip RUNNING for fast tools
    },
    ToolExecutionStatus.RUNNING: {
        ToolExecutionStatus.COMPLETED,     # Skip OBSERVING if no post-processing
    },
}


def validate_tool_execution_transition(
    current: ToolExecutionStatus,
    target: ToolExecutionStatus,
) -> None:
    """Validate a tool execution state transition.

    Raises ValidationError if the transition is not allowed.
    """
    if current == target:
        return

    allowed = _VALID_TRANSITIONS.get(current, set())
    shortcuts = _SHORTCUT_TRANSITIONS.get(current, set())
    all_allowed = allowed | shortcuts

    if target not in all_allowed:
        raise ValidationError(
            f"Invalid tool execution transition from {current.value} to {target.value}.",
            metadata={
                "current_status": current.value,
                "target_status": target.value,
                "allowed": [s.value for s in all_allowed],
            },
        )


def is_terminal(status: ToolExecutionStatus) -> bool:
    """Check if a status is a terminal state."""
    return status in (
        ToolExecutionStatus.COMPLETED,
        ToolExecutionStatus.FAILED,
        ToolExecutionStatus.CANCELLED,
    )