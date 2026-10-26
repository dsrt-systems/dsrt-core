"""
World Lifecycle Manager (C7 §6).

Deterministic state machine for World instances.

Lifecycle:
    REGISTERED → VALIDATING → READY → PROVISIONING → STARTING → RUNNING (or ACTIVE)
                                                                   │
               ┌───────────────────────┬───────────────────────────┤
               ▼                       ▼                           ▼
       PAUSING → PAUSED       RESETTING → RUNNING         SNAPSHOTTING → RUNNING
            │                                                      │
            ▼                                                      ▼
        RESUMING → RUNNING                                     DESTROYING → DESTROYED
"""

from __future__ import annotations

from schemas.domain.enums import WorldStatus


_VALID_TRANSITIONS: dict[str, set[str]] = {
    WorldStatus.REGISTERED.value: {
        WorldStatus.VALIDATING.value,
        WorldStatus.READY.value,
        WorldStatus.PROVISIONING.value,
        WorldStatus.DESTROYED.value,
    },
    WorldStatus.VALIDATING.value: {
        WorldStatus.READY.value,
        WorldStatus.FAILED.value,
        WorldStatus.DESTROYED.value,
    },
    WorldStatus.READY.value: {
        WorldStatus.PROVISIONING.value,
        WorldStatus.STARTING.value,
        WorldStatus.RUNNING.value,
        WorldStatus.ACTIVE.value,
        WorldStatus.DESTROYING.value,
        WorldStatus.DESTROYED.value,
    },
    WorldStatus.PROVISIONING.value: {
        WorldStatus.READY.value,
        WorldStatus.STARTING.value,
        WorldStatus.RUNNING.value,
        WorldStatus.ACTIVE.value,
        WorldStatus.FAILED.value,
        WorldStatus.DESTROYING.value,
        WorldStatus.DESTROYED.value,
    },
    WorldStatus.STARTING.value: {
        WorldStatus.RUNNING.value,
        WorldStatus.ACTIVE.value,
        WorldStatus.FAILED.value,
        WorldStatus.DESTROYING.value,
    },
    WorldStatus.RUNNING.value: {
        WorldStatus.PAUSING.value,
        WorldStatus.PAUSED.value,
        WorldStatus.RESETTING.value,
        WorldStatus.SNAPSHOTTING.value,
        WorldStatus.FAILED.value,
        WorldStatus.DESTROYING.value,
        WorldStatus.DESTROYED.value,
        WorldStatus.ACTIVE.value,
    },
    WorldStatus.ACTIVE.value: {
        WorldStatus.PAUSING.value,
        WorldStatus.PAUSED.value,
        WorldStatus.RESETTING.value,
        WorldStatus.SNAPSHOTTING.value,
        WorldStatus.FAILED.value,
        WorldStatus.DESTROYING.value,
        WorldStatus.DESTROYED.value,
        WorldStatus.RUNNING.value,
    },
    WorldStatus.PAUSING.value: {
        WorldStatus.PAUSED.value,
        WorldStatus.FAILED.value,
        WorldStatus.DESTROYING.value,
    },
    WorldStatus.PAUSED.value: {
        WorldStatus.RESUMING.value,
        WorldStatus.RUNNING.value,
        WorldStatus.ACTIVE.value,
        WorldStatus.DESTROYING.value,
        WorldStatus.DESTROYED.value,
    },
    WorldStatus.RESUMING.value: {
        WorldStatus.RUNNING.value,
        WorldStatus.ACTIVE.value,
        WorldStatus.FAILED.value,
        WorldStatus.DESTROYING.value,
    },
    WorldStatus.RESETTING.value: {
        WorldStatus.READY.value,
        WorldStatus.RUNNING.value,
        WorldStatus.ACTIVE.value,
        WorldStatus.FAILED.value,
        WorldStatus.DESTROYING.value,
    },
    WorldStatus.SNAPSHOTTING.value: {
        WorldStatus.RUNNING.value,
        WorldStatus.ACTIVE.value,
        WorldStatus.FAILED.value,
        WorldStatus.DESTROYING.value,
    },
    WorldStatus.FAILED.value: {
        WorldStatus.RESETTING.value,
        WorldStatus.PROVISIONING.value,
        WorldStatus.DESTROYING.value,
        WorldStatus.DESTROYED.value,
    },
    WorldStatus.DESTROYING.value: {
        WorldStatus.DESTROYED.value,
        WorldStatus.FAILED.value,
    },
    WorldStatus.DESTROYED.value: set(),
}

TERMINAL_STATES = frozenset({WorldStatus.DESTROYED.value})


class WorldLifecycleManager:
    """Validates and governs World state machine transitions (C7 §6)."""

    @staticmethod
    def validate_transition(current: str, target: str) -> None:
        """Raise ValueError if the transition is illegal."""
        if current == target:
            return

        allowed = _VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise ValueError(
                f"Invalid world transition: '{current}' -> '{target}'. "
                f"Allowed from '{current}': {sorted(allowed)}"
            )

    @staticmethod
    def is_terminal(status: str) -> bool:
        """Check if status is terminal (DESTROYED)."""
        return status in TERMINAL_STATES