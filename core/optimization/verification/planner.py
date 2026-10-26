"""
Planner module for C11.7 Verification Optimizer.

Maps task risk, complexity, and constraints to optimal verification strategies,
instantiating and pruning candidate steps.

SAFETY FIX (C11.9): Mandatory security checks cannot be pruned under budget
constraints when policy requires them.
"""

from typing import Dict, List, Optional, Tuple
from schemas.domain.verification_optimization import (
    VerificationTier,
    VerificationStrategyType,
    VerificationStep,
    VerificationOptimizationRequest,
)
from core.optimization.verification.cascade import VerificationCascadeEngine
from core.optimization.verification.evaluator import VerificationEvaluator


# Mandatory tiers that cannot be pruned when security policy requires them
MANDATORY_SECURITY_TIERS = {VerificationTier.SECURITY_SCAN}

# Default catalog of standard verification tools per tier
DEFAULT_STEP_CATALOG: Dict[VerificationTier, VerificationStep] = {
    VerificationTier.SYNTAX_LINT: VerificationStep(
        tier=VerificationTier.SYNTAX_LINT,
        tool_name="ruff_linter",
        estimated_cost=0.001,
        estimated_latency_sec=0.2,
        failure_detection_prob=0.35,
        required_pass_score=1.0,
        is_blocking=True,
        parameters={"fix": False, "select": ["E", "F"]},
    ),
    VerificationTier.UNIT_TEST: VerificationStep(
        tier=VerificationTier.UNIT_TEST,
        tool_name="pytest_runner",
        estimated_cost=0.010,
        estimated_latency_sec=2.0,
        failure_detection_prob=0.60,
        required_pass_score=1.0,
        is_blocking=True,
        parameters={"timeout_sec": 30},
    ),
    VerificationTier.STATIC_ANALYSIS: VerificationStep(
        tier=VerificationTier.STATIC_ANALYSIS,
        tool_name="mypy_checker",
        estimated_cost=0.005,
        estimated_latency_sec=1.5,
        failure_detection_prob=0.45,
        required_pass_score=1.0,
        is_blocking=False,
        parameters={"strict": True},
    ),
    VerificationTier.INTEGRATION_TEST: VerificationStep(
        tier=VerificationTier.INTEGRATION_TEST,
        tool_name="pytest_integration",
        estimated_cost=0.050,
        estimated_latency_sec=10.0,
        failure_detection_prob=0.75,
        required_pass_score=1.0,
        is_blocking=True,
        parameters={"env": "sandbox"},
    ),
    VerificationTier.SECURITY_SCAN: VerificationStep(
        tier=VerificationTier.SECURITY_SCAN,
        tool_name="bandit_security",
        estimated_cost=0.020,
        estimated_latency_sec=3.0,
        failure_detection_prob=0.50,
        required_pass_score=1.0,
        is_blocking=True,
        parameters={"severity_level": "medium"},
    ),
    VerificationTier.PROPERTY_TEST: VerificationStep(
        tier=VerificationTier.PROPERTY_TEST,
        tool_name="hypothesis_runner",
        estimated_cost=0.040,
        estimated_latency_sec=6.0,
        failure_detection_prob=0.65,
        required_pass_score=1.0,
        is_blocking=False,
        parameters={"max_examples": 100},
    ),
    VerificationTier.CONSENSUS_VERIFICATION: VerificationStep(
        tier=VerificationTier.CONSENSUS_VERIFICATION,
        tool_name="multi_agent_reviewer",
        estimated_cost=0.150,
        estimated_latency_sec=15.0,
        failure_detection_prob=0.85,
        required_pass_score=0.80,
        is_blocking=True,
        parameters={"consensus_threshold": 0.8},
    ),
}


class VerificationPlanner:
    """Generates and adapts verification plans based on task attributes and budget limits."""

    def __init__(self, step_catalog: Optional[Dict[VerificationTier, VerificationStep]] = None):
        self.catalog = step_catalog or DEFAULT_STEP_CATALOG

    def select_strategy_type(
        self, complexity_score: float, risk_level: float
    ) -> VerificationStrategyType:
        """Determines verification strategy based on risk and complexity scores."""
        combined_score = (complexity_score * 0.4) + (risk_level * 0.6)

        if combined_score <= 0.25:
            return VerificationStrategyType.MINIMAL
        elif combined_score <= 0.55:
            return VerificationStrategyType.BALANCED
        elif combined_score <= 0.80:
            return VerificationStrategyType.THOROUGH
        else:
            return VerificationStrategyType.EXHAUSTIVE

    def get_tiers_for_strategy(
        self, strategy: VerificationStrategyType
    ) -> List[VerificationTier]:
        """Returns baseline tiers associated with a strategy preset."""
        if strategy == VerificationStrategyType.MINIMAL:
            return [VerificationTier.SYNTAX_LINT, VerificationTier.UNIT_TEST]
        elif strategy == VerificationStrategyType.BALANCED:
            return [
                VerificationTier.SYNTAX_LINT,
                VerificationTier.UNIT_TEST,
                VerificationTier.STATIC_ANALYSIS,
            ]
        elif strategy == VerificationStrategyType.THOROUGH:
            return [
                VerificationTier.SYNTAX_LINT,
                VerificationTier.UNIT_TEST,
                VerificationTier.STATIC_ANALYSIS,
                VerificationTier.INTEGRATION_TEST,
                VerificationTier.SECURITY_SCAN,
            ]
        elif strategy == VerificationStrategyType.EXHAUSTIVE:
            return [
                VerificationTier.SYNTAX_LINT,
                VerificationTier.UNIT_TEST,
                VerificationTier.STATIC_ANALYSIS,
                VerificationTier.INTEGRATION_TEST,
                VerificationTier.SECURITY_SCAN,
                VerificationTier.PROPERTY_TEST,
                VerificationTier.CONSENSUS_VERIFICATION,
            ]
        else:  # ADAPTIVE
            return [
                VerificationTier.SYNTAX_LINT,
                VerificationTier.UNIT_TEST,
                VerificationTier.STATIC_ANALYSIS,
                VerificationTier.INTEGRATION_TEST,
            ]

    def create_candidate_steps(self, tiers: List[VerificationTier]) -> List[VerificationStep]:
        """Instantiates step configurations for active tiers from catalog."""
        steps = []
        for tier in tiers:
            if tier in self.catalog:
                step_copy = self.catalog[tier].model_copy(deep=True)
                steps.append(step_copy)
        return steps

    def adapt_steps_to_constraints(
        self,
        steps: List[VerificationStep],
        request: VerificationOptimizationRequest,
        require_mandatory_security_checks: bool = True,
    ) -> Tuple[List[VerificationStep], bool]:
        """
        Prunes or adjusts steps if max cost or latency constraints are breached.

        SAFETY FIX: When require_mandatory_security_checks=True, security tiers
        are never pruned, even if budget is exceeded. The pipeline will exceed
        budget and raise a visible warning instead of silently removing security.
        """
        pruned = False
        active_steps = list(steps)

        def exceeds_constraints(step_list: List[VerificationStep]) -> bool:
            c = VerificationEvaluator.calculate_pipeline_cost(step_list)
            l = VerificationEvaluator.calculate_pipeline_latency(step_list)
            if request.max_allowed_cost is not None and c > request.max_allowed_cost:
                return True
            if request.max_allowed_latency_sec is not None and l > request.max_allowed_latency_sec:
                return True
            return False

        if not exceeds_constraints(active_steps):
            return active_steps, False

        # Build removal order based on policy
        # Mandatory security tiers are placed LAST (or excluded if policy requires them)
        base_removal_order = [VerificationTier.CONSENSUS_VERIFICATION, VerificationTier.PROPERTY_TEST, VerificationTier.INTEGRATION_TEST, VerificationTier.STATIC_ANALYSIS, VerificationTier.SYNTAX_LINT, VerificationTier.UNIT_TEST]

        if require_mandatory_security_checks:
            # SECURITY_SCAN is NEVER in removal order when policy requires it
            removal_order = base_removal_order
        else:
            # Only when policy explicitly allows, security may be pruned last-resort
            removal_order = base_removal_order + [VerificationTier.SECURITY_SCAN]

        for tier_to_remove in removal_order:
            if not exceeds_constraints(active_steps):
                break
            filtered = [s for s in active_steps if s.tier != tier_to_remove]
            if filtered:
                active_steps = filtered
                pruned = True

        return active_steps, pruned
