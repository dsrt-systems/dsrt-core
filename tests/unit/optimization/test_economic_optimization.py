"""
C11.5 — Economic Optimization Engine unit tests.

Validates:
  1. Cost estimation (seven-component model)
  2. Constraint checking (Q, R, L, B)
  3. Objective scoring under Economy / Balanced / Quality policies
  4. End-to-end optimizer: feasible selection, infeasible handling
  5. Budget execution limits generation
  6. Prediction record generation
  7. Edge cases: single candidate, all infeasible, no cost data
  8. ORM model DDL (SQLite)

Total: 17 test cases.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from core.storage.database import Base

# --- SQLite JSONB compatibility ---
@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "TEXT"

# IMPORT MODELS TO REGISTER WITH BASE.METADATA BEFORE create_all()
from core.storage.models.optimization_c11 import (
    OptimizationPlanModel,
    PredictionRecordModel,
)

from schemas.domain.task_intelligence import (
    TaskClassification,
    TaskComplexityScore,
    TaskProfile,
)
from schemas.domain.economic_optimization import (
    BudgetExecutionLimits,
    CostBreakdown,
    ExecutionConfigCandidate,
    FeasibilityStatus,
    OptimizationConstraints,
    OptimizationPolicy,
    PlanStatus,
)
from core.optimization.economics.cost_estimator import CostEstimator
from core.optimization.economics.constraints import ConstraintChecker
from core.optimization.economics.objective import ObjectiveScorer
from core.optimization.economics.optimizer import EconomicOptimizer


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture(scope="module")
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    eng = eng.execution_options(schema_translate_map={"dsrt": None})
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture(scope="module")
def session_factory(engine):
    return sessionmaker(bind=engine)


@pytest.fixture()
def session(session_factory):
    sess = session_factory()
    yield sess
    sess.rollback()
    sess.close()


def _make_task_profile(complexity_val: float = 0.5) -> TaskProfile:
    """Use model_construct to bypass strict validation in unit tests."""
    cscore = TaskComplexityScore.model_construct(
        score=complexity_val,
        level="medium",
        factors={}
    )
    cclass = TaskClassification.model_construct(
        primary_domain="software_engineering",
        primary_intent="bug_fixing",
        task_type="code_modification",
        confidence=0.85,
    )
    
    return TaskProfile.model_construct(
        task_id=str(uuid.uuid4()),
        profile_id=str(uuid.uuid4()),
        organization_id="org-123",
        complexity=cscore,
        complexity_score=cscore,
        classification=cclass,
        risk=None,
        constraints=None,
        dependencies=None
    )


def _make_candidate(
    cid: str,
    tier: str = "tier_2",
    quality: float | None = 0.85,
    reliability: float | None = 0.90,
    latency_ms: int | None = 5000,
    evidence_n: int = 50,
    confidence: float | None = 0.8,
    strategies: list[str] | None = None,
    tools: list[str] | None = None,
    verification: str = "V2",
    cost_breakdown: CostBreakdown | None = None,
) -> ExecutionConfigCandidate:
    return ExecutionConfigCandidate(
        candidate_id=cid,
        model_fingerprint=f"model-{cid}",
        model_display_name=f"Model {cid}",
        connection_id=f"conn-{cid}",
        agent_id="software_engineering",
        agent_version="1.0",
        strategies=strategies or ["context_retrieval", "verification"],
        tools=tools or ["file_system", "shell", "code_execution"],
        environments=["sandbox"],
        verification_level=verification,
        estimated_quality=quality,
        estimated_reliability=reliability,
        estimated_latency_ms=latency_ms,
        evidence_sample_size=evidence_n,
        evidence_confidence=confidence,
        cost_breakdown=cost_breakdown or CostBreakdown(),
        metadata={"model_tier": tier},
    )


# ===================================================================
# Test 1: Cost estimator produces seven-component breakdown
# ===================================================================

class TestCostEstimator:
    def test_seven_component_breakdown(self):
        estimator = CostEstimator()
        profile = _make_task_profile(0.5)
        breakdown = estimator.estimate(
            task_profile=profile,
            model_fingerprint="model-A",
            model_tier="tier_2",
            strategies=["context_retrieval", "verification", "task_decomposition"],
            tools=["file_system", "shell", "code_execution"],
            verification_level="V2",
            agent_id="software_engineering",
        )

        assert breakdown.model_cost > 0, "Model cost must be positive"
        assert breakdown.planning_cost > 0, "Planning cost must be positive"
        assert breakdown.retrieval_cost > 0, "Retrieval cost must be positive"
        assert breakdown.tool_cost > 0, "Tool cost must be positive"
        assert breakdown.environment_cost > 0, "Environment cost for compute tools"
        assert breakdown.verification_cost > 0, "Verification cost must be positive"
        assert breakdown.recovery_cost > 0, "Recovery cost must be positive"
        assert breakdown.total > 0, "Total must be positive"
        assert breakdown.total == pytest.approx(
            breakdown.model_cost + breakdown.planning_cost +
            breakdown.retrieval_cost + breakdown.tool_cost +
            breakdown.environment_cost + breakdown.verification_cost +
            breakdown.recovery_cost,
            abs=1e-6,
        )

    def test_higher_tier_costs_more(self):
        estimator = CostEstimator()
        profile = _make_task_profile(0.5)
        cheap = estimator.estimate(
            task_profile=profile, model_fingerprint="m1",
            model_tier="tier_1", strategies=[], tools=[], verification_level="V0",
        )
        expensive = estimator.estimate(
            task_profile=profile, model_fingerprint="m2",
            model_tier="tier_4", strategies=[], tools=[], verification_level="V0",
        )
        assert expensive.model_cost > cheap.model_cost

    def test_higher_complexity_costs_more(self):
        estimator = CostEstimator()
        simple = estimator.estimate(
            task_profile=_make_task_profile(0.1),
            model_fingerprint="m1", model_tier="tier_2",
            strategies=[], tools=["shell"], verification_level="V1",
        )
        complex_ = estimator.estimate(
            task_profile=_make_task_profile(0.9),
            model_fingerprint="m1", model_tier="tier_2",
            strategies=[], tools=["shell"], verification_level="V1",
        )
        assert complex_.total > simple.total


# ===================================================================
# Test 2: Constraint checker
# ===================================================================

class TestConstraintChecker:
    def test_feasible_candidate(self):
        checker = ConstraintChecker()
        candidate = _make_candidate("A", quality=0.90, reliability=0.95)
        candidate.cost_breakdown = CostBreakdown(model_cost=0.05)
        constraints = OptimizationConstraints(
            min_quality=0.85, min_reliability=0.90,
            max_latency_ms=10000, max_budget=0.50,
        )
        result = checker.check(candidate, constraints)
        assert result.status == FeasibilityStatus.FEASIBLE
        assert len(result.violations) == 0

    def test_infeasible_quality(self):
        checker = ConstraintChecker()
        candidate = _make_candidate("B", quality=0.60, reliability=0.95)
        candidate.cost_breakdown = CostBreakdown(model_cost=0.01)
        constraints = OptimizationConstraints(min_quality=0.85)
        result = checker.check(candidate, constraints)
        assert result.status == FeasibilityStatus.INFEASIBLE_QUALITY

    def test_infeasible_budget(self):
        checker = ConstraintChecker()
        candidate = _make_candidate("C", quality=0.90, reliability=0.95)
        candidate.cost_breakdown = CostBreakdown(model_cost=0.80)
        constraints = OptimizationConstraints(max_budget=0.10)
        result = checker.check(candidate, constraints)
        assert result.status == FeasibilityStatus.INFEASIBLE_BUDGET

    def test_infeasible_multiple(self):
        checker = ConstraintChecker()
        candidate = _make_candidate("D", quality=0.50, reliability=0.40, latency_ms=90000)
        candidate.cost_breakdown = CostBreakdown(model_cost=5.0)
        constraints = OptimizationConstraints(
            min_quality=0.85, min_reliability=0.90,
            max_latency_ms=10000, max_budget=0.50,
        )
        result = checker.check(candidate, constraints)
        assert result.status == FeasibilityStatus.INFEASIBLE_MULTIPLE
        assert len(result.violations) >= 2


# ===================================================================
# Test 3: Objective scorer under different policies
# ===================================================================

class TestObjectiveScorer:
    def test_economy_prefers_cheaper(self):
        scorer = ObjectiveScorer()
        checker = ConstraintChecker()
        constraints = OptimizationConstraints(min_quality=0.70)

        cheap = _make_candidate("cheap", quality=0.80, reliability=0.85, evidence_n=100, confidence=0.9)
        cheap.cost_breakdown = CostBreakdown(model_cost=0.02)

        expensive = _make_candidate("expensive", quality=0.92, reliability=0.95, evidence_n=100, confidence=0.9)
        expensive.cost_breakdown = CostBreakdown(model_cost=0.15)

        s_cheap = scorer.score(cheap, checker.check(cheap, constraints), OptimizationPolicy.ECONOMY)
        s_expensive = scorer.score(expensive, checker.check(expensive, constraints), OptimizationPolicy.ECONOMY)

        assert s_cheap.objective_score > s_expensive.objective_score, (
            "Economy policy should prefer the cheaper candidate"
        )

    def test_quality_prefers_better(self):
        scorer = ObjectiveScorer()
        checker = ConstraintChecker()
        constraints = OptimizationConstraints()

        mediocre = _make_candidate("med", quality=0.70, reliability=0.75, evidence_n=100, confidence=0.9)
        mediocre.cost_breakdown = CostBreakdown(model_cost=0.02)

        excellent = _make_candidate("exc", quality=0.96, reliability=0.98, evidence_n=100, confidence=0.9)
        excellent.cost_breakdown = CostBreakdown(model_cost=0.10)

        s_med = scorer.score(mediocre, checker.check(mediocre, constraints), OptimizationPolicy.QUALITY)
        s_exc = scorer.score(excellent, checker.check(excellent, constraints), OptimizationPolicy.QUALITY)

        assert s_exc.objective_score > s_med.objective_score, (
            "Quality policy should prefer the higher-quality candidate"
        )

    def test_infeasible_scores_zero(self):
        scorer = ObjectiveScorer()
        checker = ConstraintChecker()
        candidate = _make_candidate("bad", quality=0.30)
        candidate.cost_breakdown = CostBreakdown(model_cost=0.01)
        constraints = OptimizationConstraints(min_quality=0.85)
        feas = checker.check(candidate, constraints)
        scored = scorer.score(candidate, feas, OptimizationPolicy.BALANCED)
        assert scored.objective_score == 0.0


# ===================================================================
# Test 4: End-to-end optimizer
# ===================================================================

class TestEconomicOptimizer:
    def test_selects_best_feasible(self):
        optimizer = EconomicOptimizer()
        profile = _make_task_profile(0.5)
        constraints = OptimizationConstraints(
            min_quality=0.80, min_reliability=0.80,
            max_budget=0.50,
        )

        candidates = [
            _make_candidate("A", tier="tier_1", quality=0.75, reliability=0.90),  # infeasible quality
            _make_candidate("B", tier="tier_2", quality=0.88, reliability=0.92),  # feasible
            _make_candidate("C", tier="tier_3", quality=0.95, reliability=0.97),  # feasible, better
        ]

        plan = optimizer.optimize(
            task_profile=profile,
            candidates=candidates,
            constraints=constraints,
            policy=OptimizationPolicy.BALANCED,
        )

        assert plan.status == PlanStatus.PROPOSED
        assert plan.selected_candidate.candidate_id != "A"
        assert plan.estimated_cost is not None
        assert plan.estimated_cost > 0
        assert len(plan.decision_reasons) > 0

    def test_all_infeasible_returns_least_infeasible(self):
        optimizer = EconomicOptimizer()
        profile = _make_task_profile(0.5)
        constraints = OptimizationConstraints(
            min_quality=0.99, min_reliability=0.99,
            max_budget=0.001,
        )
        candidates = [
            _make_candidate("X", quality=0.70, reliability=0.70),
            _make_candidate("Y", quality=0.80, reliability=0.80),
        ]
        plan = optimizer.optimize(
            task_profile=profile,
            candidates=candidates,
            constraints=constraints,
        )
        assert plan.status == PlanStatus.DRAFT
        assert any("infeasible" in r.lower() or "No feasible" in r for r in plan.decision_reasons)
        assert len(plan.limitations) > 0

    def test_budget_limits_generated(self):
        optimizer = EconomicOptimizer()
        profile = _make_task_profile(0.5)
        constraints = OptimizationConstraints(
            min_quality=0.70, max_budget=1.00,
        )
        candidates = [_make_candidate("Z", tier="tier_2", quality=0.85)]

        plan = optimizer.optimize(
            task_profile=profile,
            candidates=candidates,
            constraints=constraints,
        )
        limits = plan.budget_limits
        assert isinstance(limits, BudgetExecutionLimits)
        assert limits.total_authorized_cost > 0
        assert limits.max_model_calls > 0
        assert limits.max_retries >= 0

    def test_prediction_records_created(self):
        optimizer = EconomicOptimizer()
        profile = _make_task_profile(0.5)
        constraints = OptimizationConstraints(min_quality=0.70)
        candidates = [
            _make_candidate("P1", quality=0.85),
            _make_candidate("P2", quality=0.90),
        ]
        plan = optimizer.optimize(
            task_profile=profile,
            candidates=candidates,
            constraints=constraints,
        )
        records = optimizer.create_prediction_records(plan)
        assert len(records) >= 1
        selected_record = records[0]
        assert selected_record.optimization_id == plan.optimization_id
        assert selected_record.predicted_cost is not None

    def test_empty_candidates_raises(self):
        optimizer = EconomicOptimizer()
        profile = _make_task_profile(0.5)
        with pytest.raises(ValueError, match="At least one candidate"):
            optimizer.optimize(
                task_profile=profile,
                candidates=[],
                constraints=OptimizationConstraints(),
            )

    def test_economy_vs_quality_selects_differently(self):
        optimizer = EconomicOptimizer()
        profile = _make_task_profile(0.5)
        constraints = OptimizationConstraints(min_quality=0.70)

        cheap = _make_candidate(
            "cheap", tier="tier_1", quality=0.80, reliability=0.85,
            evidence_n=100, confidence=0.9,
        )
        expensive = _make_candidate(
            "expensive", tier="tier_4", quality=0.96, reliability=0.98,
            evidence_n=100, confidence=0.9,
        )

        plan_econ = optimizer.optimize(
            task_profile=profile,
            candidates=[cheap, expensive],
            constraints=constraints,
            policy=OptimizationPolicy.ECONOMY,
        )
        plan_qual = optimizer.optimize(
            task_profile=profile,
            candidates=[cheap, expensive],
            constraints=constraints,
            policy=OptimizationPolicy.QUALITY,
        )

        assert plan_econ.selected_candidate.candidate_id == "cheap"
        assert plan_qual.selected_candidate.candidate_id == "expensive"


# ===================================================================
# Test 5: ORM DDL smoke test
# ===================================================================

class TestOrmModels:
    def test_tables_created(self, session: Session):
        """Verify optimization_plans and prediction_records tables exist."""
        # Insert a plan
        plan = OptimizationPlanModel(
            id=str(uuid.uuid4()),
            optimization_id=str(uuid.uuid4()),
            plan_version="1",
            task_profile_id="tp-1",
            workspace_id="ws-1",
            selected_candidate_json='{"candidate_id":"c1"}',
            optimization_policy="balanced",
            status="proposed",
        )
        session.add(plan)
        session.flush()

        # Insert a prediction record
        pred = PredictionRecordModel(
            id=str(uuid.uuid4()),
            optimization_id=plan.optimization_id,
            candidate_id="c1",
            predicted_quality=0.85,
            predicted_cost=0.05,
        )
        session.add(pred)
        session.flush()

        fetched_plan = session.query(OptimizationPlanModel).filter_by(
            optimization_id=plan.optimization_id
        ).first()
        assert fetched_plan is not None
        assert fetched_plan.status == "proposed"

        fetched_pred = session.query(PredictionRecordModel).filter_by(
            optimization_id=plan.optimization_id
        ).first()
        assert fetched_pred is not None
        assert fetched_pred.predicted_quality == 0.85