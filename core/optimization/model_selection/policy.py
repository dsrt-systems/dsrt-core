"""
Phase C11.3: Model Selection Policy & Utility Evaluator

Computes multi-objective utility scores U(m) based on task profiles, optimization goals,
cost estimates, latency estimates, expected quality, and reliability metrics.
"""

from typing import Dict
from schemas.domain.task_intelligence import OptimizationGoal
from schemas.domain.model_selection import ModelCandidate, FeasibilityCheckResult


class SelectionPolicyEvaluator:
    """Evaluates candidate model utility under multi-objective optimization goals."""

    # Utility Goal Weight Matrices: (Quality, Reliability, Cost, Latency)
    GOAL_WEIGHTS: Dict[OptimizationGoal, Dict[str, float]] = {
        OptimizationGoal.MINIMIZE_COST: {"quality": 0.25, "reliability": 0.15, "cost": 0.50, "latency": 0.10},
        OptimizationGoal.MAXIMIZE_QUALITY: {"quality": 0.50, "reliability": 0.30, "cost": 0.10, "latency": 0.10},
        OptimizationGoal.MAXIMIZE_RELIABILITY: {"quality": 0.30, "reliability": 0.50, "cost": 0.10, "latency": 0.10},
        OptimizationGoal.MINIMIZE_LATENCY: {"quality": 0.20, "reliability": 0.15, "cost": 0.15, "latency": 0.50},
        OptimizationGoal.BALANCED: {"quality": 0.30, "reliability": 0.25, "cost": 0.25, "latency": 0.20},
    }

    def compute_estimated_cost(
        self,
        candidate: ModelCandidate,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        input_cost = (input_tokens / 1000.0) * candidate.cost_per_1k_input_tokens_usd
        output_cost = (output_tokens / 1000.0) * candidate.cost_per_1k_output_tokens_usd
        return round(input_cost + output_cost, 6)

    def calculate_utility_score(
        self,
        feasibility: FeasibilityCheckResult,
        goal: OptimizationGoal,
        max_budget_ref: float = 0.10,
        max_latency_ref: float = 5000.0,
    ) -> float:
        if not feasibility.is_feasible:
            return 0.0

        weights = self.GOAL_WEIGHTS.get(goal, self.GOAL_WEIGHTS[OptimizationGoal.BALANCED])

        # Normalized Quality [0.0, 1.0]
        q_norm = min(1.0, max(0.0, feasibility.expected_quality))

        # Normalized Reliability [0.0, 1.0]
        r_norm = min(1.0, max(0.0, feasibility.expected_reliability))

        # Normalized Cost Utility [0.0, 1.0]: 1.0 when cost=0, decreasing as cost approaches budget ref
        cost_ratio = feasibility.estimated_cost_usd / max(0.0001, max_budget_ref)
        c_norm = max(0.0, 1.0 - min(1.0, cost_ratio))

        # Normalized Latency Utility [0.0, 1.0]: 1.0 when latency=0, decreasing as latency approaches max_latency
        lat_ratio = feasibility.estimated_latency_ms / max(1.0, max_latency_ref)
        l_norm = max(0.0, 1.0 - min(1.0, lat_ratio))

        utility = (
            weights["quality"] * q_norm +
            weights["reliability"] * r_norm +
            weights["cost"] * c_norm +
            weights["latency"] * l_norm
        )

        return round(min(1.0, max(0.0, utility)), 4)