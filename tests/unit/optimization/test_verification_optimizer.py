"""
Unit tests for C11.7 Verification Optimizer.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

# SQLite compilation workaround for PostgreSQL JSONB
@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "TEXT"

from core.storage.database import Base
# Import ORM models to register metadata prior to create_all
from core.storage.models.optimization_c11 import VerificationPipelineModel

from schemas.domain.verification_optimization import (
    VerificationTier,
    VerificationStrategyType,
    VerificationStep,
    VerificationOptimizationRequest,
)
from core.optimization.verification.evaluator import VerificationEvaluator
from core.optimization.verification.cascade import VerificationCascadeEngine
from core.optimization.verification.planner import VerificationPlanner
from core.optimization.verification.optimizer import VerificationOptimizer


@pytest.fixture
def db_session():
    """Sets up an in-memory SQLite database session with translated schema."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    engine = engine.execution_options(schema_translate_map={"dsrt": None})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_low_risk_strategy_selection():
    """Verifies low complexity and low risk tasks yield a MINIMAL strategy."""
    planner = VerificationPlanner()
    strategy = planner.select_strategy_type(complexity_score=0.1, risk_level=0.1)
    assert strategy == VerificationStrategyType.MINIMAL

    tiers = planner.get_tiers_for_strategy(strategy)
    assert VerificationTier.SYNTAX_LINT in tiers
    assert VerificationTier.UNIT_TEST in tiers
    assert VerificationTier.SECURITY_SCAN not in tiers


def test_high_risk_strategy_selection():
    """Verifies high complexity and high risk tasks yield an EXHAUSTIVE strategy."""
    planner = VerificationPlanner()
    strategy = planner.select_strategy_type(complexity_score=0.9, risk_level=0.9)
    assert strategy == VerificationStrategyType.EXHAUSTIVE

    tiers = planner.get_tiers_for_strategy(strategy)
    assert VerificationTier.CONSENSUS_VERIFICATION in tiers
    assert VerificationTier.SECURITY_SCAN in tiers


def test_cascade_ordering_efficiency():
    """Verifies fast, high-detection blocking steps precede slow or non-blocking steps."""
    step_cheap_fast = VerificationStep(
        tier=VerificationTier.SYNTAX_LINT,
        tool_name="fast_lint",
        estimated_cost=0.001,
        estimated_latency_sec=0.1,
        failure_detection_prob=0.4,
        is_blocking=True,
    )
    step_expensive_slow = VerificationStep(
        tier=VerificationTier.CONSENSUS_VERIFICATION,
        tool_name="slow_consensus",
        estimated_cost=0.200,
        estimated_latency_sec=20.0,
        failure_detection_prob=0.8,
        is_blocking=True,
    )
    step_non_blocking = VerificationStep(
        tier=VerificationTier.STATIC_ANALYSIS,
        tool_name="static_check",
        estimated_cost=0.001,
        estimated_latency_sec=0.1,
        failure_detection_prob=0.9,
        is_blocking=False,
    )

    steps = [step_expensive_slow, step_non_blocking, step_cheap_fast]
    ordered = VerificationCascadeEngine.optimize_cascade_sequence(steps)

    # First step should be cheap fast blocking, followed by expensive blocking, then non-blocking
    assert ordered[0].tier == VerificationTier.SYNTAX_LINT
    assert ordered[1].tier == VerificationTier.CONSENSUS_VERIFICATION
    assert ordered[2].tier == VerificationTier.STATIC_ANALYSIS


def test_budget_constraint_pruning():
    """Verifies strict max cost constraints trigger adaptive tier pruning."""
    planner = VerificationPlanner()
    req = VerificationOptimizationRequest(
        task_id="task-budget-1",
        complexity_score=0.9,
        risk_level=0.9,
        max_allowed_cost=0.05,  # Excludes high-cost consensus (0.15) & integration (0.05)
    )

    baseline_tiers = planner.get_tiers_for_strategy(VerificationStrategyType.EXHAUSTIVE)
    steps = planner.create_candidate_steps(baseline_tiers)

    adapted_steps, pruned = planner.adapt_steps_to_constraints(steps, req)
    assert pruned is True

    cost = VerificationEvaluator.calculate_pipeline_cost(adapted_steps)
    assert cost <= req.max_allowed_cost


def test_latency_constraint_pruning():
    """Verifies strict max latency constraints trigger adaptive tier pruning."""
    planner = VerificationPlanner()
    req = VerificationOptimizationRequest(
        task_id="task-lat-1",
        complexity_score=0.9,
        risk_level=0.9,
        max_allowed_latency_sec=5.0,  # Excludes long steps like consensus (15s) and integration (10s)
    )

    baseline_tiers = planner.get_tiers_for_strategy(VerificationStrategyType.EXHAUSTIVE)
    steps = planner.create_candidate_steps(baseline_tiers)

    adapted_steps, pruned = planner.adapt_steps_to_constraints(steps, req)
    assert pruned is True

    latency = VerificationEvaluator.calculate_pipeline_latency(adapted_steps)
    assert latency <= req.max_allowed_latency_sec


def test_optimizer_end_to_end_and_persistence(db_session):
    """Verifies full optimization flow, plan creation, and SQLite persistence."""
    optimizer = VerificationOptimizer(db_session=db_session)
    req = VerificationOptimizationRequest(
        task_id="task-e2e-100",
        complexity_score=0.6,
        risk_level=0.6,
        target_confidence=0.85,
    )

    plan = optimizer.optimize_verification(req)

    assert plan.task_id == "task-e2e-100"
    assert plan.selected_strategy in (
        VerificationStrategyType.THOROUGH,
        VerificationStrategyType.BALANCED,
    )
    assert plan.expected_confidence >= 0.80
    assert plan.estimated_cost > 0.0
    assert plan.estimated_latency_sec > 0.0
    assert len(plan.pipeline.steps) > 0

    # Verify DB persistence
    db_record = optimizer.get_pipeline(plan.pipeline.pipeline_id)
    assert db_record is not None
    assert db_record.task_id == "task-e2e-100"
    assert db_record.expected_confidence == plan.expected_confidence
    assert len(db_record.steps_json) == len(plan.pipeline.steps)


def test_evaluator_confidence_and_utility():
    """Verifies confidence accumulation and score formulation in evaluator."""
    steps = [
        VerificationStep(
            tier=VerificationTier.SYNTAX_LINT,
            tool_name="lint",
            estimated_cost=0.01,
            estimated_latency_sec=0.5,
            failure_detection_prob=0.5,
        ),
        VerificationStep(
            tier=VerificationTier.UNIT_TEST,
            tool_name="unittest",
            estimated_cost=0.02,
            estimated_latency_sec=1.0,
            failure_detection_prob=0.5,
        ),
    ]

    # Base confidence = 0.50
    # Combined detection: 1 - (1 - 0.5)*(1 - 0.5)*(1 - 0.5) = 1 - 0.5 * 0.5 * 0.5 = 1 - 0.125 = 0.875
    conf = VerificationEvaluator.calculate_expected_confidence(steps, base_confidence=0.50)
    assert conf == 0.8750

    req = VerificationOptimizationRequest(task_id="t1", target_confidence=0.80)
    utility = VerificationEvaluator.score_pipeline_utility(steps, req)
    assert utility > 0.0