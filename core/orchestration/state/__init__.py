"""
Shared State Engine (C5 §19-23).

Versioned shared state with JSON Pointer patches, optimistic concurrency,
and conflict detection. Multiple agents can safely read and update the
shared orchestration state without corrupting each other's work.
"""

from core.orchestration.state.concurrency import (
    ConcurrencyConflict,
    OptimisticConcurrencyControl,
)
from core.orchestration.state.patches import (
    PatchApplicationError,
    StatePatchValidator,
)
from core.orchestration.state.state_store import SharedStateStore

__all__ = [
    "ConcurrencyConflict",
    "OptimisticConcurrencyControl",
    "PatchApplicationError",
    "SharedStateStore",
    "StatePatchValidator",
]