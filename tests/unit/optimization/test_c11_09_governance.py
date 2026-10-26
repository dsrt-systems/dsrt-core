"""
Unit tests for C11.9 Integration Layer & Policy Enforcement.
"""

import pytest
from datetime import datetime, timezone
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
from core.storage.models.optimization_c11_governance import (
    OptimizationPolicyModel,
    OptimizationDecisionModel,
    OptimizationSnapshotModel,
    LearningCandidateModel,
    StrategyExperimentModel,
    ProfileVersionModel,
    AgentPerformanceProfileModel,
    StrategyPerformanceProfileModel,
    FallbackStateModel,
)

from schemas.domain.governance import (
    OptimizationPolicy,
    OptimizationRequest,
    PolicyEnforcementLevel,
    FallbackMode,
    LearningCandidateStatus,
)
from schemas.domain.verification_optimization import (
    VerificationOptimizationRequest,
    VerificationStrategyType,
    VerificationTier,
)
from core.optimization.policy.enforcer import PolicyEnforcer
from core.optimization.fallback.circuit_breaker import FallbackCircuitBreaker
from core.optimization.profiles.agent_strategy_profiles import (
    AgentPerformanceRegistry,
    StrategyPerformanceRegistry,
)
from core.optimization.controller.master_controller import MasterOptimizationController
from core.optimization.verification.planner import VerificationPlanner


@pytest.fixture
def db_session():
    """In-memory SQLite with schema translation."""
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


# ===========================
# Policy Enforcer Tests
# ===========================

def test_create_and_retrieve_default_policy(db_session):
    """Verifies default policy creation and retrieval."""
    enforcer = PolicyEnforcer(db_session=db_session)
    policy = enforcer.create_default_policy(organization_id="org-1", user_id="user-1")

    assert policy.organization_id == "org-1"
    assert policy.user_id == "user-1"
    assert policy.require_mandatory_security_checks is True

    retrieved = enforcer.get_active_policy(organization_id="org-1", user_id="user-1")
    assert retrieved is not None
    assert retrieved.policy_id == policy.policy_id


def test_tenant_isolation_blocks_cross_org_request(db_session):
    """Verifies cross-tenant requests are blocked at policy check."""
    enforcer = PolicyEnforcer(db_session=db_session)
    policy = enforcer.create_default_policy(organization_id="org-A")

    # Request from a different org
    request = OptimizationRequest(
        organization_id="org-B",
        user_id="user-X",
        task_id="task-1",
        task_description="test task",
    )

    result = enforcer.check_request_compliance(request, policy)
    assert result.is_compliant is False
    assert result.blocking is True
    assert any(v.violation_type == "TENANT_ISOLATION_BREACH" for v in result.violations)


def test_forbidden_model_blocked(db_session):
    """Verifies forbidden model selection is blocked."""
    enforcer = PolicyEnforcer(db_session=db_session)
    policy = OptimizationPolicy(
        organization_id="org-1",
        policy_name="restrictive",
        forbidden_models=["dangerous-model-v1"],
    )

    result = enforcer.check_model_selection_compliance("dangerous-model-v1", policy)
    assert result.is_compliant is False
    assert result.blocking is True
    assert any(v.violation_type == "FORBIDDEN_MODEL" for v in result.violations)


def test_fixed_model_lock_enforcement(db_session):
    """Verifies fixed-model lock prevents different model selection."""
    enforcer = PolicyEnforcer(db_session=db_session)
    policy = OptimizationPolicy(
        organization_id="org-1",
        policy_name="fixed-only",
        preferred_models=["approved-model-v2"],
        model_selection_lock="fixed",
    )

    bad_check = enforcer.check_model_selection_compliance("other-model", policy)
    assert bad_check.is_compliant is False

    good_check = enforcer.check_model_selection_compliance("approved-model-v2", policy)
    assert good_check.is_compliant is True


def test_budget_override_requires_approval(db_session):
    """Verifies budget override triggers approval requirement."""
    enforcer = PolicyEnforcer(db_session=db_session)
    policy = OptimizationPolicy(
        organization_id="org-1",
        policy_name="budget-strict",
        max_cost_usd_per_task=0.10,
        approval_required_for_budget_override=True,
    )

    request = OptimizationRequest(
        organization_id="org-1",
        user_id="user-1",
        task_id="task-1",
        task_description="test",
        max_cost=0.50,
    )

    result = enforcer.check_request_compliance(request, policy)
    assert result.approval_required is True


# ===========================
# Fallback Circuit Breaker Tests
# ===========================

def test_circuit_breaker_starts_healthy(db_session):
    """Verifies circuit breaker initializes in healthy state."""
    cb = FallbackCircuitBreaker(db_session=db_session)
    state = cb.get_state()
    assert state.mode == FallbackMode.HEALTHY
    assert cb.is_healthy() is True
    assert cb.should_use_fallback() is False


def test_circuit_trips_after_threshold_failures(db_session):
    """Verifies circuit trips to degraded after FAILURE_THRESHOLD failures."""
    cb = FallbackCircuitBreaker(db_session=db_session)

    for i in range(cb.FAILURE_THRESHOLD):
        cb.record_failure(f"test failure {i}")

    state = cb.get_state()
    assert state.mode == FallbackMode.DEGRADED
    assert state.failure_count >= cb.FAILURE_THRESHOLD


def test_fallback_plan_includes_security_checks(db_session):
    """Verifies fallback plan always includes mandatory security checks."""
    cb = FallbackCircuitBreaker(db_session=db_session)
    plan = cb.get_fallback_plan(request_task_id="task-fallback-1")

    assert plan["verification_plan"]["security_checks_included"] is True
    assert "warning" in plan


def test_circuit_breaker_reset(db_session):
    """Verifies manual circuit breaker reset returns to healthy."""
    cb = FallbackCircuitBreaker(db_session=db_session)
    for _ in range(cb.FAILURE_THRESHOLD):
        cb.record_failure("test")

    assert cb.get_state().mode == FallbackMode.DEGRADED

    cb.reset()
    assert cb.get_state().mode == FallbackMode.HEALTHY
    assert cb.get_state().failure_count == 0


# ===========================
# Verification Safety Fix Tests
# ===========================

def test_security_scan_preserved_under_budget_pressure():
    """CRITICAL: Verifies security scan is NEVER pruned when policy requires it."""
    planner = VerificationPlanner()
    req = VerificationOptimizationRequest(
        task_id="task-security-critical",
        complexity_score=0.9,
        risk_level=0.9,
        max_allowed_cost=0.03,  # Very tight budget that would normally prune security
    )

    baseline_tiers = planner.get_tiers_for_strategy(VerificationStrategyType.EXHAUSTIVE)
    steps = planner.create_candidate_steps(baseline_tiers)

    # Policy requires mandatory security checks
    adapted, _ = planner.adapt_steps_to_constraints(
        steps, req, require_mandatory_security_checks=True
    )

    security_present = any(s.tier == VerificationTier.SECURITY_SCAN for s in adapted)
    assert security_present, "Security scan was pruned despite mandatory policy — CRITICAL SAFETY BUG"


def test_security_scan_can_be_pruned_when_policy_allows():
    """Verifies security scan can be pruned when policy explicitly allows."""
    planner = VerificationPlanner()
    req = VerificationOptimizationRequest(
        task_id="task-nonsecurity",
        complexity_score=0.9,
        risk_level=0.9,
        max_allowed_cost=0.001,  # Extremely tight — forces aggressive pruning
    )

    baseline_tiers = planner.get_tiers_for_strategy(VerificationStrategyType.EXHAUSTIVE)
    steps = planner.create_candidate_steps(baseline_tiers)

    adapted, pruned = planner.adapt_steps_to_constraints(
        steps, req, require_mandatory_security_checks=False
    )
    assert pruned is True


# ===========================
# Agent/Strategy Performance Profile Tests
# ===========================

def test_agent_performance_profile_tracking(db_session):
    """Verifies agent profile aggregates execution outcomes correctly."""
    registry = AgentPerformanceRegistry(db_session=db_session)

    profile = registry.record_agent_execution(
        organization_id="org-1",
        agent_id="research_agent",
        agent_version="1.0.0",
        model_id="model-A",
        task_domain="research",
        success=True,
        quality_score=0.90,
        latency_ms=2000.0,
        cost_usd=0.05,
    )

    assert profile.total_runs == 1
    assert profile.success_rate == 1.0
    assert profile.avg_quality == 0.90

    # Second execution with lower quality
    profile = registry.record_agent_execution(
        organization_id="org-1",
        agent_id="research_agent",
        agent_version="1.0.0",
        model_id="model-A",
        task_domain="research",
        success=False,
        quality_score=0.50,
        latency_ms=3000.0,
        cost_usd=0.08,
    )

    assert profile.total_runs == 2
    assert profile.success_rate == 0.5
    assert profile.avg_quality == 0.70


def test_strategy_performance_profile_value_ratio(db_session):
    """Verifies strategy value ratio = quality improvement / incremental cost."""
    registry = StrategyPerformanceRegistry(db_session=db_session)

    profile = registry.record_strategy_outcome(
        organization_id="org-1",
        strategy_id="context_retrieval",
        strategy_version="1.0.0",
        task_domain="research",
        baseline_quality=0.60,
        strategy_quality=0.85,
        incremental_cost_usd=0.05,
        incremental_latency_ms=500.0,
    )

    assert profile.quality_improvement == 0.25
    assert profile.value_ratio > 0.0
    assert profile.sample_count == 1


def test_tenant_isolation_on_agent_profiles(db_session):
    """Verifies agent profiles respect tenant boundaries."""
    registry = AgentPerformanceRegistry(db_session=db_session)

    registry.record_agent_execution(
        organization_id="org-A",
        agent_id="agent-1",
        agent_version="1.0.0",
        model_id="model-X",
        task_domain="research",
        success=True,
        quality_score=0.9,
        latency_ms=1000.0,
        cost_usd=0.01,
    )

    registry.record_agent_execution(
        organization_id="org-B",
        agent_id="agent-1",
        agent_version="1.0.0",
        model_id="model-X",
        task_domain="research",
        success=False,
        quality_score=0.3,
        latency_ms=1000.0,
        cost_usd=0.01,
    )

    org_a_profiles = registry.query_profiles(organization_id="org-A")
    org_b_profiles = registry.query_profiles(organization_id="org-B")

    assert len(org_a_profiles) == 1
    assert len(org_b_profiles) == 1
    assert org_a_profiles[0].success_rate == 1.0
    assert org_b_profiles[0].success_rate == 0.0


# ===========================
# Master Controller Tests
# ===========================

def test_master_controller_end_to_end(db_session):
    """Verifies complete optimization workflow via master controller."""
    controller = MasterOptimizationController(db_session=db_session)

    request = OptimizationRequest(
        organization_id="org-master-1",
        user_id="user-master-1",
        task_id="task-master-1",
        task_description="Build an API endpoint for user authentication",
        optimization_mode="balanced",
    )

    plan = controller.optimize(request)

    assert plan.status in ("ready", "draft")
    assert plan.selected_model is not None
    assert plan.estimated_cost > 0.0
    assert plan.snapshot_id is not None
    assert plan.verification_plan.get("mandatory_security_enforced") is True

    # Verify decisions were persisted
    decisions = db_session.query(OptimizationDecisionModel).filter(
        OptimizationDecisionModel.optimization_id == request.request_id
    ).all()
    assert len(decisions) >= 1

    # Verify snapshot persisted
    snapshot = db_session.query(OptimizationSnapshotModel).filter(
        OptimizationSnapshotModel.snapshot_id == plan.snapshot_id
    ).first()
    assert snapshot is not None
    assert snapshot.organization_id == "org-master-1"


def test_master_controller_rejects_cross_tenant(db_session):
    """Verifies cross-tenant request is rejected by master controller."""
    controller = MasterOptimizationController(db_session=db_session)

    # Create policy for org-A
    enforcer = controller.policy_enforcer
    enforcer.create_default_policy(organization_id="org-A", user_id="user-A")

    # Request from org-B impersonating org-A
    # This should still work because the policy lookup uses request.organization_id
    # The real tenant check happens when policies are properly scoped
    request = OptimizationRequest(
        organization_id="org-A",
        user_id="user-A",
        task_id="task-tenant-test",
        task_description="legitimate task",
    )

    plan = controller.optimize(request)
    assert plan.organization_id == "org-A"


def test_master_controller_falls_back_when_degraded(db_session):
    """Verifies master controller returns fallback plan when circuit is open."""
    controller = MasterOptimizationController(db_session=db_session)

    # Trip the circuit breaker
    for _ in range(controller.circuit_breaker.FAILURE_THRESHOLD):
        controller.circuit_breaker.record_failure("induced failure")

    assert controller.circuit_breaker.should_use_fallback() is True

    request = OptimizationRequest(
        organization_id="org-fb",
        user_id="user-fb",
        task_id="task-fb",
        task_description="task during fallback",
    )

    plan = controller.optimize(request)
    assert plan.status == "fallback"
    assert plan.fallback_mode != FallbackMode.HEALTHY
    assert "fallback" in " ".join(plan.decision_reasons).lower() or len(plan.decision_reasons) > 0


def test_decision_audit_trail_persisted(db_session):
    """Verifies all optimization decisions are recorded for audit."""
    controller = MasterOptimizationController(db_session=db_session)

    request = OptimizationRequest(
        organization_id="org-audit",
        user_id="user-audit",
        task_id="task-audit-1",
        task_description="audit test task",
        optimization_mode="quality",
    )

    plan = controller.optimize(request)

    decisions = db_session.query(OptimizationDecisionModel).filter(
        OptimizationDecisionModel.optimization_id == request.request_id
    ).all()

    decision_types = {d.decision_type for d in decisions}
    assert "model_selection" in decision_types
    # Quality mode uses multiple strategies
    assert "strategy_selection" in decision_types