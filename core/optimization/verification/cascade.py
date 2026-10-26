"""
Cascade engine for C11.7 Verification Optimizer.

Ranks and orders verification steps to execute high-detection, fast-failing, cheap steps
first, minimizing total downstream execution cost upon early failure.
"""

from typing import List
from schemas.domain.verification_optimization import VerificationStep


class VerificationCascadeEngine:
    """Optimizes step ordering to construct early-stopping verification cascades."""

    @staticmethod
    def calculate_efficiency_score(step: VerificationStep) -> float:
        """
        Calculates step efficiency ratio: Detection Probability / (Cost * Latency).
        Higher score indicates higher priority to run early in the cascade.
        """
        denom = (step.estimated_cost + 0.001) * (step.estimated_latency_sec + 0.1)
        return step.failure_detection_prob / denom

    @classmethod
    def optimize_cascade_sequence(
        cls, steps: List[VerificationStep]
    ) -> List[VerificationStep]:
        """
        Orders steps in optimal cascade sequence:
        1. Blocking steps sorted by efficiency score (descending).
        2. Non-blocking steps appended at the end sorted by efficiency score.
        """
        if not steps:
            return []

        blocking_steps = [s for s in steps if s.is_blocking]
        non_blocking_steps = [s for s in steps if not s.is_blocking]

        sorted_blocking = sorted(
            blocking_steps,
            key=lambda s: cls.calculate_efficiency_score(s),
            reverse=True,
        )

        sorted_non_blocking = sorted(
            non_blocking_steps,
            key=lambda s: cls.calculate_efficiency_score(s),
            reverse=True,
        )

        return sorted_blocking + sorted_non_blocking