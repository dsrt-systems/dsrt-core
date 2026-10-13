"""
Recovery Manager (C5 §30-32, §70-71).

Handles node failures through policy-driven retry, fallback,
reassignment, and heartbeat-based stale detection.
"""

from core.orchestration.recovery.recovery import (
    FailureClassification,
    RecoveryDecision,
    RecoveryManager,
)

__all__ = ["FailureClassification", "RecoveryDecision", "RecoveryManager"]