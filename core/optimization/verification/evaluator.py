"""
Evaluator module for C11.7 Verification Optimizer.

Calculates confidence levels, pipeline costs, latencies, and diminishing returns
for combinations of verification tiers.
"""

from typing import List
from schemas.domain.verification_optimization import (
    VerificationStep,
    VerificationOptimizationRequest,
)


class VerificationEvaluator:
    """Evaluates verification pipeline parameters, confidence scores, and utility metrics."""

    @staticmethod
    def calculate_pipeline_cost(steps: List[VerificationStep]) -> float:
        """Calculates total estimated USD cost across all steps."""
        return sum(step.estimated_cost for step in steps)

    @staticmethod
    def calculate_pipeline_latency(steps: List[VerificationStep]) -> float:
        """Calculates total expected latency in seconds across all steps."""
        return sum(step.estimated_latency_sec for step in steps)

    @staticmethod
    def calculate_expected_confidence(
        steps: List[VerificationStep], base_confidence: float = 0.50
    ) -> float:
        """
        Calculates cumulative post-verification confidence based on step detection probabilities.

        Model: Confidence = 1 - (1 - base_confidence) * Product(1 - step.failure_detection_prob)
        Returns a float between [0.0, 1.0].
        """
        if not steps:
            return round(base_confidence, 4)

        residual_risk = 1.0 - base_confidence
        for step in steps:
            residual_risk *= (1.0 - step.failure_detection_prob)

        confidence = 1.0 - residual_risk
        return round(min(1.0, max(0.0, confidence)), 4)

    @staticmethod
    def calculate_cost_savings(
        selected_cost: float, baseline_cost: float
    ) -> float:
        """Calculates relative cost savings against baseline (exhaustive) verification."""
        if baseline_cost <= 0.0:
            return 0.0
        savings = (baseline_cost - selected_cost) / baseline_cost
        return round(max(0.0, savings), 4)

    @classmethod
    def score_pipeline_utility(
        cls,
        steps: List[VerificationStep],
        request: VerificationOptimizationRequest,
        baseline_cost: float = 0.50,
    ) -> float:
        """
        Calculates a unified trade-off utility score balancing confidence gains against cost and latency penalties.
        """
        confidence = cls.calculate_expected_confidence(steps)
        cost = cls.calculate_pipeline_cost(steps)
        latency = cls.calculate_pipeline_latency(steps)

        # Penalties for exceeding budget/latency bounds
        cost_penalty = 0.0
        if request.max_allowed_cost is not None and cost > request.max_allowed_cost:
            cost_penalty = ((cost - request.max_allowed_cost) / request.max_allowed_cost) * 2.0

        latency_penalty = 0.0
        if request.max_allowed_latency_sec is not None and latency > request.max_allowed_latency_sec:
            latency_penalty = ((latency - request.max_allowed_latency_sec) / request.max_allowed_latency_sec) * 2.0

        confidence_shortfall = max(0.0, request.target_confidence - confidence) * 3.0

        # Score formulation: utility ranges from 0.0 to 1.0+
        utility = (
            (confidence * 0.6)
            + ((1.0 - min(1.0, cost / max(1.0, baseline_cost))) * 0.4)
            - cost_penalty
            - latency_penalty
            - confidence_shortfall
        )
        return round(max(0.0, utility), 4)