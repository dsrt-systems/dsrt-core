"""
Node Lifecycle Manager (C5 §10).

Deterministic state machine for node execution lifecycle.

Valid transitions (C5 §10):
  PENDING   → READY
  READY     → QUEUED
  QUEUED    → RUNNING
  RUNNING   → VERIFYING | FAILED | CANCELLING
  VERIFYING → COMPLETED | FAILED
  FAILED    → RETRYING | BLOCKED
  RETRYING  → RUNNING
  RUNNING   → CANCELLING
  CANCELLING → CANCELLED
  PENDING   → SKIPPED

Invalid transitions raise ValueError.
"""

from __future__ import annotations

from schemas.domain.enums import NodeStatus


# Valid transitions: from_status -> set of allowed to_statuses
_VALID_TRANSITIONS: dict[str, set[str]] = {
    NodeStatus.PENDING.value: {
        NodeStatus.READY.value,
        NodeStatus.SKIPPED.value,
        NodeStatus.CANCELLED.value,
    },
    NodeStatus.READY.value: {
        NodeStatus.QUEUED.value,
        NodeStatus.RUNNING.value,
        NodeStatus.SKIPPED.value,
        NodeStatus.CANCELLED.value,
    },
    NodeStatus.QUEUED.value: {
        NodeStatus.RUNNING.value,
        NodeStatus.CANCELLED.value,
    },
    NodeStatus.RUNNING.value: {
        NodeStatus.VERIFYING.value,
        NodeStatus.FAILED.value,
        NodeStatus.CANCELLING.value,
        NodeStatus.COMPLETED.value,  # Direct completion for simple nodes
    },
    NodeStatus.VERIFYING.value: {
        NodeStatus.COMPLETED.value,
        NodeStatus.FAILED.value,
    },
    NodeStatus.FAILED.value: {
        NodeStatus.RETRYING.value,
        NodeStatus.BLOCKED.value,
        NodeStatus.CANCELLED.value,
    },
    NodeStatus.RETRYING.value: {
        NodeStatus.RUNNING.value,
        NodeStatus.CANCELLED.value,
    },
    NodeStatus.BLOCKED.value: {
        NodeStatus.CANCELLED.value,
    },
    NodeStatus.CANCELLING.value: {
        NodeStatus.CANCELLED.value,
    },
    # Terminal states — no outgoing transitions
    NodeStatus.COMPLETED.value: set(),
    NodeStatus.CANCELLED.value: set(),
    NodeStatus.SKIPPED.value: set(),
}

TERMINAL_STATES = frozenset({
    NodeStatus.COMPLETED.value,
    NodeStatus.FAILED.value,
    NodeStatus.CANCELLED.value,
    NodeStatus.BLOCKED.value,
    NodeStatus.SKIPPED.value,
})


class NodeLifecycleManager:
    """Validates and manages node state transitions (C5 §10)."""

    @staticmethod
    def validate_transition(
        current: str, target: str,
    ) -> None:
        """Validate a state transition. Raises ValueError if invalid."""
        if current == target:
            return  # No-op transitions are allowed

        allowed = _VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise ValueError(
                f"Invalid node transition: {current} -> {target}. "
                f"Allowed from {current}: {sorted(allowed)}"
            )

    @staticmethod
    def is_terminal(status: str) -> bool:
        """Check if a status is a terminal state."""
        return status in TERMINAL_STATES

    @staticmethod
    def can_retry(status: str, attempt: int, max_attempts: int) -> bool:
        """Check if a failed node can be retried."""
        return (
            status == NodeStatus.FAILED.value
            and attempt < max_attempts
        )

    @staticmethod
    def next_status_after_failure(
        attempt: int, max_attempts: int,
    ) -> str:
        """Determine the next status after a node failure."""
        if attempt < max_attempts:
            return NodeStatus.RETRYING.value
        return NodeStatus.FAILED.value