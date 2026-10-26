"""
Reward module for C11.8 Strategy Learning Engine.

Calculates multi-objective unified scalar rewards normalized into [0.0, 1.0].
Balances output quality gains against cost and latency penalties.
"""

from typing import Optional
from schemas.domain.strategy_learning import RewardSignal, StrategyFeedbackRequest


class RewardCalculator:
    """Calculates scalar reward signals combining quality, cost, and latency metrics."""

    @staticmethod
    def compute_reward(feedback: StrategyFeedbackRequest) -> RewardSignal:
        """
        Computes normalized scalar reward:
        Reward = w_q * QualityScore + w_c * (1 - CostPenalty) + w_l * (1 - LatencyPenalty)

        Weights: w_q = 0.60, w_c = 0.25, w_l = 0.15
        """
        w_quality = 0.60
        w_cost = 0.25
        w_latency = 0.15

        # 1. Quality contribution
        quality_component = max(0.0, min(1.0, feedback.quality_score))

        # 2. Cost penalty calculation
        cost_penalty = 0.0
        if feedback.max_budget_cost and feedback.max_budget_cost > 0:
            if feedback.cost_usd > feedback.max_budget_cost:
                excess_ratio = (feedback.cost_usd - feedback.max_budget_cost) / feedback.max_budget_cost
                cost_penalty = min(1.0, excess_ratio)
            else:
                cost_penalty = max(0.0, feedback.cost_usd / (feedback.max_budget_cost * 2.0))
        else:
            # Baseline reference cost = $0.10
            cost_penalty = min(1.0, feedback.cost_usd / 0.10)

        # 3. Latency penalty calculation
        latency_penalty = 0.0
        if feedback.max_allowed_latency_ms and feedback.max_allowed_latency_ms > 0:
            if feedback.latency_ms > feedback.max_allowed_latency_ms:
                excess_ratio = (feedback.latency_ms - feedback.max_allowed_latency_ms) / feedback.max_allowed_latency_ms
                latency_penalty = min(1.0, excess_ratio)
            else:
                latency_penalty = max(0.0, feedback.latency_ms / (feedback.max_allowed_latency_ms * 2.0))
        else:
            # Baseline reference latency = 5000 ms
            latency_penalty = min(1.0, feedback.latency_ms / 5000.0)

        # 4. Unified Scalar Reward
        reward = (
            (w_quality * quality_component)
            + (w_cost * (1.0 - cost_penalty))
            + (w_latency * (1.0 - latency_penalty))
        )
        normalized_reward = round(max(0.0, min(1.0, reward)), 4)

        return RewardSignal(
            strategy_id=feedback.strategy_id,
            task_id=feedback.task_id,
            quality_score=feedback.quality_score,
            cost_usd=feedback.cost_usd,
            latency_ms=feedback.latency_ms,
            normalized_cost_penalty=round(cost_penalty, 4),
            normalized_latency_penalty=round(latency_penalty, 4),
            scalar_reward=normalized_reward,
        )