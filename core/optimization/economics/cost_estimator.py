"""
C11.5 — Cost Estimator.

Estimates total execution cost for a candidate configuration
using the seven-component cost model from the spec §6A:

    C_total = C_model + C_planning + C_retrieval + C_tools
              + C_environment + C_verification + C_recovery
"""

from __future__ import annotations

import logging
from typing import Any

from schemas.domain.economic_optimization import CostBreakdown
from schemas.domain.task_intelligence import (
    TaskComplexityScore,
    TaskProfile,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-component rate tables (production: sourced from C2/C3/C10 ledger)
# ---------------------------------------------------------------------------

_MODEL_TIER_COSTS: dict[str, float] = {
    "tier_1": 0.002,
    "tier_2": 0.008,
    "tier_3": 0.025,
    "tier_4": 0.060,
    "unknown": 0.015,
}

_CALLS_BY_COMPLEXITY: dict[str, int] = {
    "trivial": 1,
    "low": 2,
    "medium": 4,
    "high": 8,
    "very_high": 14,
}

_STRATEGY_COST_MULTIPLIERS: dict[str, float] = {
    "task_decomposition": 0.30,
    "structured_planning": 0.15,
    "context_retrieval": 0.20,
    "domain_knowledge_injection": 0.10,
    "evidence_grounding": 0.25,
    "tool_grounded_execution": 0.35,
    "parallel_subtasks": 0.40,
    "result_integration": 0.15,
    "verification": 0.20,
    "targeted_repair": 0.25,
    "model_escalation": 0.50,
}

_TOOL_COSTS: dict[str, float] = {
    "web_search": 0.003,
    "browser": 0.010,
    "code_execution": 0.005,
    "shell": 0.002,
    "file_system": 0.001,
    "database": 0.004,
    "api_call": 0.005,
}

_VERIFICATION_COSTS: dict[str, float] = {
    "V0": 0.001,
    "V1": 0.005,
    "V2": 0.015,
    "V3": 0.030,
    "V4": 0.060,
    "V5": 0.100,
}


def _complexity_band(score: float) -> str:
    if score < 0.15:
        return "trivial"
    if score < 0.35:
        return "low"
    if score < 0.60:
        return "medium"
    if score < 0.80:
        return "high"
    return "very_high"


class CostEstimator:
    def __init__(
        self,
        model_tier_costs: dict[str, float] | None = None,
        strategy_multipliers: dict[str, float] | None = None,
        tool_costs: dict[str, float] | None = None,
        verification_costs: dict[str, float] | None = None,
    ) -> None:
        self._model_costs = model_tier_costs or dict(_MODEL_TIER_COSTS)
        self._strategy_mults = strategy_multipliers or dict(_STRATEGY_COST_MULTIPLIERS)
        self._tool_costs = tool_costs or dict(_TOOL_COSTS)
        self._verification_costs = verification_costs or dict(_VERIFICATION_COSTS)

    def estimate(
        self,
        task_profile: TaskProfile,
        model_fingerprint: str,
        model_tier: str = "unknown",
        strategies: list[str] | None = None,
        tools: list[str] | None = None,
        verification_level: str = "V1",
        agent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CostBreakdown:
        strategies = strategies or []
        tools = tools or []
        complexity = self._extract_complexity(task_profile)
        band = _complexity_band(complexity)

        model_cost = self._estimate_model_cost(model_tier, band)
        planning_cost = self._estimate_planning_cost(
            model_tier, band, strategies, agent_id
        )
        retrieval_cost = self._estimate_retrieval_cost(strategies, band)
        tool_cost = self._estimate_tool_cost(tools, band)
        environment_cost = self._estimate_environment_cost(tools, band)
        verification_cost = self._estimate_verification_cost(verification_level)
        recovery_cost = self._estimate_recovery_cost(
            model_cost + planning_cost + retrieval_cost + tool_cost,
            complexity,
            strategies,
        )

        breakdown = CostBreakdown(
            model_cost=round(model_cost, 6),
            planning_cost=round(planning_cost, 6),
            retrieval_cost=round(retrieval_cost, 6),
            tool_cost=round(tool_cost, 6),
            environment_cost=round(environment_cost, 6),
            verification_cost=round(verification_cost, 6),
            recovery_cost=round(recovery_cost, 6),
        )

        logger.debug(
            "Cost estimate for model=%s tier=%s band=%s => $%.4f",
            model_fingerprint, model_tier, band, breakdown.total,
        )
        return breakdown

    def _extract_complexity(self, profile: TaskProfile) -> float:
        """Robustly extract complexity score from TaskProfile."""
        cscore = None
        if hasattr(profile, "complexity") and profile.complexity is not None:
            cscore = profile.complexity
        elif hasattr(profile, "complexity_score") and profile.complexity_score is not None:
            cscore = profile.complexity_score

        if cscore is not None:
            if hasattr(cscore, "score"):
                return float(cscore.score)
            if hasattr(cscore, "composite"):
                return float(cscore.composite)
            try:
                return float(cscore)
            except (ValueError, TypeError):
                pass
        return 0.5

    def _estimate_model_cost(self, tier: str, band: str) -> float:
        per_call = self._model_costs.get(tier, self._model_costs["unknown"])
        calls = _CALLS_BY_COMPLEXITY.get(band, 4)
        return per_call * calls

    def _estimate_planning_cost(
        self,
        tier: str,
        band: str,
        strategies: list[str],
        agent_id: str | None,
    ) -> float:
        per_call = self._model_costs.get(tier, self._model_costs["unknown"])
        planning_calls = 1
        if "task_decomposition" in strategies:
            planning_calls += 1
        if "structured_planning" in strategies:
            planning_calls += 1
        if agent_id:
            planning_calls += 1
        return per_call * planning_calls

    def _estimate_retrieval_cost(self, strategies: list[str], band: str) -> float:
        base = 0.002
        if "context_retrieval" in strategies:
            base += 0.005
        if "domain_knowledge_injection" in strategies:
            base += 0.003
        if "evidence_grounding" in strategies:
            base += 0.004
        scale = _CALLS_BY_COMPLEXITY.get(band, 4) / 4.0
        return base * scale

    def _estimate_tool_cost(self, tools: list[str], band: str) -> float:
        total = 0.0
        invocations = max(1, _CALLS_BY_COMPLEXITY.get(band, 4) // 2)
        for tool in tools:
            per_use = self._tool_costs.get(tool, 0.003)
            total += per_use * invocations
        return total

    def _estimate_environment_cost(self, tools: list[str], band: str) -> float:
        compute_tools = {"code_execution", "shell", "browser"}
        has_compute = any(t in compute_tools for t in tools)
        if not has_compute:
            return 0.0
        base = 0.005
        scale = _CALLS_BY_COMPLEXITY.get(band, 4) / 4.0
        return base * scale

    def _estimate_verification_cost(self, level: str) -> float:
        return self._verification_costs.get(level, 0.005)

    def _estimate_recovery_cost(
        self,
        base_execution_cost: float,
        complexity: float,
        strategies: list[str],
    ) -> float:
        failure_prob = min(0.6, complexity * 0.5)
        if "targeted_repair" in strategies:
            failure_prob *= 0.7
        if "model_escalation" in strategies:
            escalation_extra = base_execution_cost * 0.4
        else:
            escalation_extra = 0.0

        retry_cost = base_execution_cost * failure_prob
        return retry_cost + escalation_extra * failure_prob