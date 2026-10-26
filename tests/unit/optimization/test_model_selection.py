"""
Unit tests for C11.3 Adaptive Model Selector
Verifies utility scoring, feasibility checks, AUTOMATIC / USER_PREFERRED / FIXED selection modes,
substitution reasoning, fallback logic, and performance registry integration.
"""

import pytest
import uuid

from schemas.domain.task_intelligence import (
    TaskProfile,
    TaskClassification,
    TaskComplexityScore,
    TaskRiskProfile,
    TaskConstraintSet,
    TaskConstraint,
    TaskDependencyGraph,
    TaskDomain,
    TaskIntent,
    TaskComplexityLevel,
    RiskLevel,
    OptimizationGoal,
)
from schemas.domain.model_selection import (
    ModelCandidate,
    ModelSelectionMode,
    ModelSelectionRequest,
    ModelTier,
    SubstitutionReason,
)
from schemas.domain.performance_intelligence import PerformanceProfile, PerformanceMetrics, FailureAnalysisResult
from core.optimization.model_selection import (
    AdaptiveModelSelector,
    SelectionPolicyEvaluator,
    ModelSubstitutionEngine,
)


@pytest.fixture
def sample_task_profile():
    return TaskProfile(
        profile_id="tp_100",
        task_id="task_100",
        organization_id="org_test",
        classification=TaskClassification(
            primary_domain=TaskDomain.SOFTWARE_ENGINEERING,
            primary_intent=TaskIntent.CODE_GENERATION,
        ),
        complexity=TaskComplexityScore(
            score=0.5,
            level=TaskComplexityLevel.MEDIUM,
        ),
        risk=TaskRiskProfile(
            overall_level=RiskLevel.LOW,
            score=0.1,
        ),
        constraints=TaskConstraintSet(
            max_budget_usd=0.05,
            max_latency_ms=3000.0,
        ),
        dependencies=TaskDependencyGraph(),
        metadata={"optimization_goal": "balanced"},
    )


@pytest.fixture
def available_candidates():
    return [
        ModelCandidate(
            model_id="gpt-4o",
            provider="openai",
            tier=ModelTier.FLAGSHIP,
            cost_per_1k_input_tokens_usd=0.0025,
            cost_per_1k_output_tokens_usd=0.0100,
            typical_latency_ms=1200.0,
        ),
        ModelCandidate(
            model_id="claude-3-5-sonnet",
            provider="anthropic",
            tier=ModelTier.FLAGSHIP,
            cost_per_1k_input_tokens_usd=0.0030,
            cost_per_1k_output_tokens_usd=0.0150,
            typical_latency_ms=1000.0,
        ),
        ModelCandidate(
            model_id="gpt-4o-mini",
            provider="openai",
            tier=ModelTier.FAST_ECONOMY,
            cost_per_1k_input_tokens_usd=0.00015,
            cost_per_1k_output_tokens_usd=0.00060,
            typical_latency_ms=400.0,
        ),
    ]


@pytest.fixture
def selector():
    return AdaptiveModelSelector()


class TestSelectionPolicyEvaluator:
    def test_compute_estimated_cost(self):
        evaluator = SelectionPolicyEvaluator()
        cand = ModelCandidate(
            model_id="m1",
            provider="p1",
            cost_per_1k_input_tokens_usd=0.001,
            cost_per_1k_output_tokens_usd=0.002,
        )
        cost = evaluator.compute_estimated_cost(cand, input_tokens=2000, output_tokens=1000)
        # (2 * 0.001) + (1 * 0.002) = 0.004
        assert cost == 0.004

    def test_calculate_utility_score_bounds(self):
        evaluator = SelectionPolicyEvaluator()
        from schemas.domain.model_selection import FeasibilityCheckResult
        fe = FeasibilityCheckResult(
            model_id="m1",
            is_feasible=True,
            estimated_cost_usd=0.001,
            estimated_latency_ms=500.0,
            expected_quality=0.90,
            expected_reliability=0.95,
        )
        u = evaluator.calculate_utility_score(fe, goal=OptimizationGoal.BALANCED)
        assert 0.0 <= u <= 1.0


class TestModelSubstitutionEngine:
    def test_determine_substitution_reason_budget(self):
        engine = ModelSubstitutionEngine()
        from schemas.domain.model_selection import FeasibilityCheckResult
        pref_eval = FeasibilityCheckResult(
            model_id="gpt-4o",
            is_feasible=False,
            violations=["Estimated cost $0.15 exceeds maximum task budget $0.05"],
        )
        pref_cand = ModelCandidate(model_id="gpt-4o", provider="openai", tier=ModelTier.FLAGSHIP)
        sel_cand = ModelCandidate(model_id="gpt-4o-mini", provider="openai", tier=ModelTier.FAST_ECONOMY)

        reason = engine.determine_substitution_reason(pref_eval, sel_cand, pref_cand)
        assert reason == SubstitutionReason.BUDGET_EXCEEDED


class TestAdaptiveModelSelector:
    def test_automatic_selection(self, selector, sample_task_profile, available_candidates):
        req = ModelSelectionRequest(
            request_id="req_auto",
            organization_id="org_test",
            task_profile=sample_task_profile,
            selection_mode=ModelSelectionMode.AUTOMATIC,
            available_candidates=available_candidates,
            estimated_input_tokens=1000,
            estimated_output_tokens=500,
        )
        decision = selector.select_model(req)
        assert decision.selected_model_id in ["gpt-4o", "claude-3-5-sonnet", "gpt-4o-mini"]
        assert decision.selection_mode == ModelSelectionMode.AUTOMATIC
        assert decision.utility_score > 0.0

    def test_user_preferred_feasible(self, selector, sample_task_profile, available_candidates):
        req = ModelSelectionRequest(
            request_id="req_pref",
            organization_id="org_test",
            task_profile=sample_task_profile,
            selection_mode=ModelSelectionMode.USER_PREFERRED,
            preferred_model_id="claude-3-5-sonnet",
            available_candidates=available_candidates,
        )
        decision = selector.select_model(req)
        assert decision.selected_model_id == "claude-3-5-sonnet"
        assert decision.was_substituted is False

    def test_user_preferred_infeasible_fallback(self, selector, sample_task_profile, available_candidates):
        # Set strict budget so flagship models fail feasibility
        constrained_profile = sample_task_profile.model_copy(
            update={
                "constraints": TaskConstraintSet(max_budget_usd=0.001)
            }
        )
        req = ModelSelectionRequest(
            request_id="req_fallback",
            organization_id="org_test",
            task_profile=constrained_profile,
            selection_mode=ModelSelectionMode.USER_PREFERRED,
            preferred_model_id="claude-3-5-sonnet",
            available_candidates=available_candidates,
            estimated_input_tokens=1000,
            estimated_output_tokens=500,
        )
        decision = selector.select_model(req)
        assert decision.selected_model_id == "gpt-4o-mini"
        assert decision.was_substituted is True
        assert decision.substitution_reason == SubstitutionReason.BUDGET_EXCEEDED

    def test_fixed_mode_success(self, selector, sample_task_profile, available_candidates):
        req = ModelSelectionRequest(
            request_id="req_fixed",
            organization_id="org_test",
            task_profile=sample_task_profile,
            selection_mode=ModelSelectionMode.FIXED,
            preferred_model_id="gpt-4o",
            available_candidates=available_candidates,
        )
        decision = selector.select_model(req)
        assert decision.selected_model_id == "gpt-4o"
        assert decision.selection_mode == ModelSelectionMode.FIXED

    def test_fixed_mode_infeasible_raises_error(self, selector, sample_task_profile, available_candidates):
        constrained_profile = sample_task_profile.model_copy(
            update={
                "constraints": TaskConstraintSet(max_budget_usd=0.0001)
            }
        )
        req = ModelSelectionRequest(
            request_id="req_fixed_fail",
            organization_id="org_test",
            task_profile=constrained_profile,
            selection_mode=ModelSelectionMode.FIXED,
            preferred_model_id="gpt-4o",
            available_candidates=available_candidates,
        )
        with pytest.raises(ValueError, match="violates hard constraints"):
            selector.select_model(req)

    def test_forbidden_model_filtering(self, selector, sample_task_profile, available_candidates):
        forbidden_profile = sample_task_profile.model_copy(
            update={
                "constraints": TaskConstraintSet(forbidden_models=["gpt-4o", "claude-3-5-sonnet"])
            }
        )
        req = ModelSelectionRequest(
            request_id="req_forbid",
            organization_id="org_test",
            task_profile=forbidden_profile,
            selection_mode=ModelSelectionMode.AUTOMATIC,
            available_candidates=available_candidates,
        )
        decision = selector.select_model(req)
        assert decision.selected_model_id == "gpt-4o-mini"