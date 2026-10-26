"""
Phase C11.3: Model Substitution Engine

Handles fallback chains, tier step-downs, tier upgrades, and explicit reasoning
for model substitutions.
"""

from typing import List, Optional, Tuple
from schemas.domain.model_selection import (
    ModelCandidate,
    FeasibilityCheckResult,
    SubstitutionReason,
    ModelTier,
)


class ModelSubstitutionEngine:
    """Manages candidate fallbacks and determines explicit substitution reasons."""

    TIER_RANKING = {
        ModelTier.FLAGSHIP: 3,
        ModelTier.MID_TIER: 2,
        ModelTier.SPECIALIZED: 2,
        ModelTier.FAST_ECONOMY: 1,
    }

    def determine_substitution_reason(
        self,
        preferred_eval: Optional[FeasibilityCheckResult],
        selected_candidate: ModelCandidate,
        preferred_candidate: Optional[ModelCandidate],
    ) -> SubstitutionReason:
        if not preferred_candidate or not preferred_eval:
            return SubstitutionReason.NONE

        if preferred_eval.is_feasible and selected_candidate.model_id == preferred_candidate.model_id:
            return SubstitutionReason.NONE

        if not preferred_eval.is_feasible:
            for v in preferred_eval.violations:
                v_lower = v.lower()
                if "budget" in v_lower or "cost" in v_lower:
                    return SubstitutionReason.BUDGET_EXCEEDED
                if "latency" in v_lower:
                    return SubstitutionReason.LATENCY_EXCEEDED
                if "context window" in v_lower:
                    return SubstitutionReason.CONTEXT_WINDOW_TOO_SMALL
                if "capability" in v_lower or "tool" in v_lower or "vision" in v_lower:
                    return SubstitutionReason.MISSING_REQUIRED_CAPABILITY
                if "forbidden" in v_lower or "not allowed" in v_lower:
                    return SubstitutionReason.MODEL_FORBIDDEN

            return SubstitutionReason.USER_PREFERRED_INFEASIBLE

        # Both feasible, but different model chosen due to utility optimization
        pref_rank = self.TIER_RANKING.get(preferred_candidate.tier, 2)
        sel_rank = self.TIER_RANKING.get(selected_candidate.tier, 2)

        if sel_rank > pref_rank:
            return SubstitutionReason.OPTIMIZATION_UPGRADE
        elif sel_rank < pref_rank:
            return SubstitutionReason.OPTIMIZATION_DOWNGRADE

        return SubstitutionReason.USER_PREFERRED_INFEASIBLE

    def find_fallback_candidate(
        self,
        feasible_evals: List[Tuple[ModelCandidate, FeasibilityCheckResult]],
    ) -> Optional[Tuple[ModelCandidate, FeasibilityCheckResult]]:
        if not feasible_evals:
            return None

        # Return feasible candidate with highest expected reliability, then quality
        sorted_candidates = sorted(
            feasible_evals,
            key=lambda item: (item[1].expected_reliability, item[1].expected_quality, -item[1].estimated_cost_usd),
            reverse=True,
        )
        return sorted_candidates[0]