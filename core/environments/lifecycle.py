"""
Environment Lifecycle State Machine (C3 §35).

Deterministic, validated state transitions for environment instances.
"""

from __future__ import annotations

from enum import Enum

from core.api.errors.exceptions import ValidationError


class EnvironmentStatus(str, Enum):
    """Lifecycle states for an environment instance (C3 §35)."""
    REQUESTED = "REQUESTED"
    PROVISIONING = "PROVISIONING"
    READY = "READY"
    ACTIVE = "ACTIVE"
    IDLE = "IDLE"
    TERMINATING = "TERMINATING"
    TERMINATED = "TERMINATED"
    FAILED = "FAILED"


_VALID_TRANSITIONS: dict[EnvironmentStatus, set[EnvironmentStatus]] = {
    EnvironmentStatus.REQUESTED: {
        EnvironmentStatus.PROVISIONING,
        EnvironmentStatus.FAILED,
    },
    EnvironmentStatus.PROVISIONING: {
        EnvironmentStatus.READY,
        EnvironmentStatus.FAILED,
    },
    EnvironmentStatus.READY: {
        EnvironmentStatus.ACTIVE,
        EnvironmentStatus.TERMINATING,
        EnvironmentStatus.FAILED,
    },
    EnvironmentStatus.ACTIVE: {
        EnvironmentStatus.IDLE,
        EnvironmentStatus.TERMINATING,
        EnvironmentStatus.FAILED,
    },
    EnvironmentStatus.IDLE: {
        EnvironmentStatus.ACTIVE,
        EnvironmentStatus.TERMINATING,
        EnvironmentStatus.FAILED,
    },
    EnvironmentStatus.TERMINATING: {
        EnvironmentStatus.TERMINATED,
        EnvironmentStatus.FAILED,
    },
    EnvironmentStatus.TERMINATED: set(),  # Terminal
    EnvironmentStatus.FAILED: set(),      # Terminal
}


def validate_environment_transition(
    current: EnvironmentStatus,
    target: EnvironmentStatus,
) -> None:
    """Validate an environment state transition.

    Raises ValidationError if the transition is not allowed.
    """
    if current == target:
        return

    allowed = _VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValidationError(
            f"Invalid environment transition from {current.value} to {target.value}.",
            metadata={
                "current_status": current.value,
                "target_status": target.value,
                "allowed": [s.value for s in allowed],
            },
        )


def is_terminal_environment_status(status: EnvironmentStatus) -> bool:
    """Check if a status is a terminal state."""
    return status in (
        EnvironmentStatus.TERMINATED,
        EnvironmentStatus.FAILED,
    )