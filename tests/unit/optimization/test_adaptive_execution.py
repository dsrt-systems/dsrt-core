"""
C11.6 — Adaptive Execution Controller unit tests.

Validates:
  1. Trigger detection across budget, context, tools, and test failures.
  2. Bounded recovery decision generation.
  3. Attempt history tracking and attempt cap enforcement.
  4. Budget exhaustion triggers STOP_EXECUTION.
  5. ORM model table persistence smoke test.

Total: 10 unit tests.
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

@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "TEXT"

from core.storage.models.optimization_c11 import AdaptationEventModel
from schemas.domain.adaptive_execution import (
    AdaptationActionType,
    AdaptationTriggerType,
    ExecutionEvent,
)
from schemas.domain.economic_optimization import (
    BudgetExecutionLimits,
    CostBreakdown,
    ExecutionConfigCandidate,
    OptimizationConstraints,
    OptimizationPlanOutput,
    OptimizationPolicy,
    PlanStatus,
)
from schemas.domain.task_intelligence import TaskProfile
from core.optimization.adaptive_execution.controller import AdaptiveExecutionController
from core.optimization.adaptive_execution.recovery import RecoveryPolicyEngine
from core.optimization.adaptive_execution.triggers import TriggerDetector


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


def _make_dummy_plan(budget: float = 1.0) -> OptimizationPlanOutput:
    task_p = TaskProfile.model_construct(task_id="t1")
    cand = ExecutionConfigCandidate(
        candidate_id="c1",
        model_fingerprint="m1",
        cost_breakdown=CostBreakdown(model_cost=0.1),
    )
    return OptimizationPlanOutput(
        optimization_id=str(uuid.uuid4()),
        task_profile_id="t1",
        selected_candidate=cand,
        authorized_budget=budget,
        budget_limits=BudgetExecutionLimits(
            total_authorized_cost=budget,
            max_retries=2,
        ),
        constraints=OptimizationConstraints(max_budget=budget),
        status=PlanStatus.PROPOSED,
    )


# ===================================================================
# Unit Tests
# ===================================================================

class TestTriggerDetector:
    def test_detects_budget_exhaustion(self):
        detector = TriggerDetector()
        plan = _make_dummy_plan(budget=0.5)
        event = ExecutionEvent(
            event_id="e1",
            execution_id="ex1",
            event_type="step_completed",
            current_cost=0.55,
        )
        trigger = detector.detect_trigger(event, plan)
        assert trigger == AdaptationTriggerType.BUDGET_EXHAUSTED

    def test_detects_test_failure(self):
        detector = TriggerDetector()
        plan = _make_dummy_plan(budget=1.0)
        event = ExecutionEvent(
            event_id="e2",
            execution_id="ex1",
            event_type="test_failed",
            error_message="AssertionError in test_main.py",
            details={"tests_failed": 2},
        )
        trigger = detector.detect_trigger(event, plan)
        assert trigger == AdaptationTriggerType.TEST_FAILURE

    def test_detects_context_limit(self):
        detector = TriggerDetector()
        plan = _make_dummy_plan()
        event = ExecutionEvent(
            event_id="e3",
            execution_id="ex1",
            event_type="model_error",
            error_message="Maximum context_length exceeded (8192 tokens)",
        )
        trigger = detector.detect_trigger(event, plan)
        assert trigger == AdaptationTriggerType.CONTEXT_LIMIT_EXCEEDED


class TestRecoveryEngine:
    def test_test_failure_recommends_bounded_repair(self):
        engine_policy = RecoveryPolicyEngine()
        plan = _make_dummy_plan()
        event = ExecutionEvent(
            event_id="e1",
            execution_id="ex1",
            event_type="test_failed",
        )
        decision = engine_policy.evaluate_recovery(
            trigger=AdaptationTriggerType.TEST_FAILURE,
            event=event,
            plan=plan,
            attempt_history={},
        )
        assert decision.recommended_action == AdaptationActionType.BOUNDED_REPAIR
        assert decision.is_bounded is True

    def test_budget_exhausted_recommends_stop(self):
        engine_policy = RecoveryPolicyEngine()
        plan = _make_dummy_plan(budget=0.1)
        event = ExecutionEvent(
            event_id="e2",
            execution_id="ex1",
            event_type="budget_cap",
            current_cost=0.15,
        )
        decision = engine_policy.evaluate_recovery(
            trigger=AdaptationTriggerType.BUDGET_EXHAUSTED,
            event=event,
            plan=plan,
            attempt_history={},
        )
        assert decision.recommended_action == AdaptationActionType.STOP_EXECUTION


class TestAdaptiveExecutionController:
    def test_observe_healthy_returns_none(self):
        controller = AdaptiveExecutionController()
        plan = _make_dummy_plan()
        event = ExecutionEvent(
            event_id="e1",
            execution_id="ex1",
            event_type="step_completed",
            current_cost=0.01,
        )
        decision = controller.observe_and_adapt(event, plan)
        assert decision is None

    def test_observe_adaptation_increments_attempts(self):
        controller = AdaptiveExecutionController()
        plan = _make_dummy_plan()
        event = ExecutionEvent(
            event_id="e1",
            execution_id="ex1",
            event_type="model_error",
            error_message="invalid JSON schema returned",
        )

        d1 = controller.observe_and_adapt(event, plan)
        assert d1 is not None
        assert d1.current_attempt == 1

        d2 = controller.observe_and_adapt(event, plan)
        assert d2 is not None
        assert d2.current_attempt == 2

    def test_exceeding_max_retries_stops_or_escalates(self):
        controller = AdaptiveExecutionController()
        plan = _make_dummy_plan()
        event = ExecutionEvent(
            event_id="e1",
            execution_id="ex1",
            event_type="test_failed",
            error_message="AssertionError",
        )

        # Retries: 1, 2, 3 (max_retries is 2)
        controller.observe_and_adapt(event, plan)
        controller.observe_and_adapt(event, plan)
        d3 = controller.observe_and_adapt(event, plan)

        assert d3 is not None
        assert d3.recommended_action == AdaptationActionType.STOP_EXECUTION


class TestOrmModel:
    def test_adaptation_event_persisted(self, session: Session):
        record = AdaptationEventModel(
            id=str(uuid.uuid4()),
            execution_id="ex-100",
            decision_id="dec-200",
            trigger_type="test_failure",
            action_type="bounded_repair",
            estimated_cost=0.01,
            reason="Tests failed during execution step 2",
        )
        session.add(record)
        session.flush()

        fetched = session.query(AdaptationEventModel).filter_by(execution_id="ex-100").first()
        assert fetched is not None
        assert fetched.action_type == "bounded_repair"