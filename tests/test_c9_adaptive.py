# tests/test_c9_adaptive.py
"""
C9.7 Fallback, Escalation & Adaptive Routing — comprehensive tests.

Covers:
  - FallbackEngine (§39–40)
  - EscalationEngine (§41)
  - AdaptiveRouteController (§36–38)
  - StageRouter (§34–35)
"""

from __future__ import annotations

import pytest

from core.routing.contracts import (
    AdaptiveRoute,
    EscalationPolicy,
    ExecutionStrategy,
    FallbackPolicy,
    Route,
    RouteCandidate,
    StageRoutePreference,
    StageRoutingConfig,
)
from core.routing.enums import (
    AdaptiveRouteState,
    EligibilityStatus,
    ExecutionStage,
    FallbackActionType,
    FallbackTriggerType,
    RejectionCategory,
)
from core.routing.adaptive.controller import (
    AdaptiveRouteController,
    AdaptationResult,
)
from core.routing.adaptive.stage_router import StageRouter
from core.routing.escalation.engine import EscalationDecision, EscalationEngine
from core.routing.fallback.engine import FallbackDecision, FallbackEngine


# ── Helpers ────────────────────────────────────────────────────────────

def _route(
    model: str = "model-a",
    provider: str = "prov-1",
) -> Route:
    return Route(
        agent_id="agent-1",
        agent_version_id="av-1",
        model_id=model,
        model_version_id="mv-1",
        provider_id=provider,
        tools=["web.search"],
    )


def _fallback_candidate(
    model: str = "model-b",
    provider: str = "prov-2",
    eligible: bool = True,
) -> RouteCandidate:
    c = RouteCandidate(
        candidate_id=f"cand-{model}",
        agent_id="agent-1",
        agent_version_id="av-1",
        model_id=model,
        model_version_id="mv-1",
        provider_id=provider,
    )
    if not eligible:
        c.reject(RejectionCategory.POLICY_DENIED, "denied")
    return c


# ═══════════════════════════════════════════════════════════════════════
# FallbackEngine
# ═══════════════════════════════════════════════════════════════════════

class TestFallbackEngine:

    def setup_method(self) -> None:
        self.fb = FallbackEngine()

    def test_retry_default(self) -> None:
        d = self.fb.evaluate(
            FallbackTriggerType.PROVIDER_TIMEOUT,
            _route(),
        )
        assert d.action == FallbackActionType.RETRY
        assert d.attempt_number == 1
        assert not d.is_terminal

    def test_retry_backoff_increases(self) -> None:
        d1 = self.fb.evaluate(
            FallbackTriggerType.GENERATION_FAILURE,
            _route(), attempt_number=1,
        )
        d2 = self.fb.evaluate(
            FallbackTriggerType.GENERATION_FAILURE,
            _route(), attempt_number=2,
        )
        assert d2.backoff_seconds > d1.backoff_seconds

    def test_max_attempts_exhausted(self) -> None:
        d = self.fb.evaluate(
            FallbackTriggerType.PROVIDER_TIMEOUT,
            _route(), attempt_number=4,
        )
        assert d.action == FallbackActionType.ABORT
        assert d.is_terminal

    def test_switch_model(self) -> None:
        pol = FallbackPolicy(
            policy_id="switch-pol",
            name="Switch",
            triggers=[FallbackTriggerType.VERIFICATION_FAILURE],
            action=FallbackActionType.SWITCH_MODEL,
            max_attempts=3,
        )
        candidates = [_fallback_candidate("model-b")]
        d = self.fb.evaluate(
            FallbackTriggerType.VERIFICATION_FAILURE,
            _route("model-a"),
            policy=pol,
            fallback_candidates=candidates,
        )
        assert d.action == FallbackActionType.SWITCH_MODEL
        assert d.next_model_id == "model-b"

    def test_switch_model_no_candidates(self) -> None:
        pol = FallbackPolicy(
            policy_id="switch-pol",
            name="Switch",
            action=FallbackActionType.SWITCH_MODEL,
        )
        d = self.fb.evaluate(
            FallbackTriggerType.GENERATION_FAILURE,
            _route(),
            policy=pol,
            fallback_candidates=[],
        )
        assert d.action == FallbackActionType.ABORT

    def test_switch_provider(self) -> None:
        pol = FallbackPolicy(
            policy_id="switch-prov",
            name="Switch Provider",
            action=FallbackActionType.SWITCH_PROVIDER,
        )
        candidates = [_fallback_candidate(provider="prov-2")]
        d = self.fb.evaluate(
            FallbackTriggerType.PROVIDER_RATE_LIMIT,
            _route(provider="prov-1"),
            policy=pol,
            fallback_candidates=candidates,
        )
        assert d.action == FallbackActionType.SWITCH_PROVIDER
        assert d.next_provider_id == "prov-2"

    def test_uncovered_trigger_aborts(self) -> None:
        pol = FallbackPolicy(
            policy_id="narrow",
            name="Narrow",
            triggers=[FallbackTriggerType.PROVIDER_TIMEOUT],
            action=FallbackActionType.RETRY,
        )
        d = self.fb.evaluate(
            FallbackTriggerType.BUDGET_EXCEEDED,
            _route(),
            policy=pol,
        )
        assert d.action == FallbackActionType.ABORT

    def test_human_approval(self) -> None:
        pol = FallbackPolicy(
            policy_id="human",
            name="Human",
            action=FallbackActionType.HUMAN_APPROVAL,
        )
        d = self.fb.evaluate(
            FallbackTriggerType.QUALITY_INSUFFICIENT,
            _route(),
            policy=pol,
        )
        assert d.action == FallbackActionType.HUMAN_APPROVAL
        assert d.is_terminal

    def test_should_escalate(self) -> None:
        assert not self.fb.should_escalate(2)
        assert self.fb.should_escalate(4)

    def test_switch_skips_ineligible(self) -> None:
        pol = FallbackPolicy(
            policy_id="sw",
            name="SW",
            action=FallbackActionType.SWITCH_MODEL,
        )
        candidates = [
            _fallback_candidate("model-x", eligible=False),
            _fallback_candidate("model-y", eligible=True),
        ]
        d = self.fb.evaluate(
            FallbackTriggerType.GENERATION_FAILURE,
            _route("model-a"),
            policy=pol,
            fallback_candidates=candidates,
        )
        assert d.next_model_id == "model-y"


# ═══════════════════════════════════════════════════════════════════════
# EscalationEngine
# ═══════════════════════════════════════════════════════════════════════

class TestEscalationEngine:

    def setup_method(self) -> None:
        self.esc = EscalationEngine()

    def test_no_escalation_needed(self) -> None:
        d = self.esc.evaluate(fallback_attempts=1, route=_route())
        assert not d.should_escalate

    def test_escalation_on_max_attempts(self) -> None:
        d = self.esc.evaluate(fallback_attempts=3, route=_route())
        assert d.should_escalate
        assert "maximum" in d.reason.lower()

    def test_escalation_security_sensitive(self) -> None:
        pol = EscalationPolicy(
            policy_id="sec",
            name="Security",
            security_sensitive=True,
        )
        d = self.esc.evaluate(
            fallback_attempts=1,
            route=_route(),
            policy=pol,
            is_security_sensitive=True,
        )
        assert d.should_escalate
        assert "security" in d.reason.lower()

    def test_no_escalation_security_not_sensitive(self) -> None:
        pol = EscalationPolicy(
            policy_id="sec",
            name="Security",
            security_sensitive=True,
        )
        d = self.esc.evaluate(
            fallback_attempts=1,
            route=_route(),
            policy=pol,
            is_security_sensitive=False,
        )
        assert not d.should_escalate

    def test_mandated_review(self) -> None:
        pol = EscalationPolicy(
            policy_id="mandated",
            name="Mandated",
            policy_mandated_review=True,
        )
        d = self.esc.evaluate(
            fallback_attempts=0,
            route=_route(),
            policy=pol,
        )
        assert d.should_escalate
        assert "mandates" in d.reason.lower()

    def test_route_model_included(self) -> None:
        d = self.esc.evaluate(
            fallback_attempts=5,
            route=_route("model-x"),
        )
        assert d.route_model_id == "model-x"


# ═══════════════════════════════════════════════════════════════════════
# AdaptiveRouteController
# ═══════════════════════════════════════════════════════════════════════

class TestAdaptiveRouteController:

    def setup_method(self) -> None:
        self.ctrl = AdaptiveRouteController()

    def test_create_adaptive_route(self) -> None:
        ar = self.ctrl.create_adaptive_route(_route())
        assert ar.state == AdaptiveRouteState.ACTIVE
        assert ar.fallback_attempts == 0

    def test_retry_on_timeout(self) -> None:
        ar = self.ctrl.create_adaptive_route(_route())
        result = self.ctrl.on_observation(
            ar, FallbackTriggerType.PROVIDER_TIMEOUT,
        )
        assert result.action_taken == "RETRY"
        assert ar.state == AdaptiveRouteState.ACTIVE

    def test_model_switch(self) -> None:
        fb = FallbackEngine(
            default_policy=FallbackPolicy(
                policy_id="sw",
                name="SW",
                triggers=list(FallbackTriggerType),
                action=FallbackActionType.SWITCH_MODEL,
                max_attempts=3,
            ),
        )
        ctrl = AdaptiveRouteController(fallback_engine=fb)
        ar = ctrl.create_adaptive_route(_route("model-a"))
        candidates = [_fallback_candidate("model-b")]
        result = ctrl.on_observation(
            ar,
            FallbackTriggerType.VERIFICATION_FAILURE,
            fallback_candidates=candidates,
        )
        assert result.action_taken == "switched"
        assert result.new_route is not None
        assert result.new_route.model_id == "model-b"
        assert ar.current_route.model_id == "model-b"
        assert len(ar.change_history) == 1
        assert ar.fallback_attempts == 1

    def test_escalation_on_exhaustion(self) -> None:
        ar = self.ctrl.create_adaptive_route(_route(), max_fallback_attempts=2)
        ar.fallback_attempts = 2  # simulate exhaustion
        result = self.ctrl.on_observation(
            ar, FallbackTriggerType.GENERATION_FAILURE,
        )
        assert result.action_taken == "escalated"
        assert ar.state == AdaptiveRouteState.ESCALATED

    def test_abort_on_terminal_state(self) -> None:
        ar = self.ctrl.create_adaptive_route(_route())
        ar.state = AdaptiveRouteState.ABORTED
        result = self.ctrl.on_observation(
            ar, FallbackTriggerType.PROVIDER_TIMEOUT,
        )
        assert result.action_taken == "no_action"

    def test_max_re_evaluation_limit(self) -> None:
        ctrl = AdaptiveRouteController(max_re_evaluations=2)
        ar = ctrl.create_adaptive_route(_route())
        ar.fallback_attempts = 2
        result = ctrl.on_observation(
            ar, FallbackTriggerType.GENERATION_FAILURE,
        )
        assert result.action_taken == "aborted"
        assert ar.state == AdaptiveRouteState.ABORTED

    def test_change_record_audit(self) -> None:
        fb = FallbackEngine(
            default_policy=FallbackPolicy(
                policy_id="sw",
                name="SW",
                triggers=list(FallbackTriggerType),
                action=FallbackActionType.SWITCH_MODEL,
                max_attempts=5,
            ),
        )
        ctrl = AdaptiveRouteController(fallback_engine=fb)
        ar = ctrl.create_adaptive_route(_route("model-a"))
        candidates = [_fallback_candidate("model-b")]
        result = ctrl.on_observation(
            ar,
            FallbackTriggerType.VERIFICATION_FAILURE,
            fallback_candidates=candidates,
        )
        assert result.change_record is not None
        assert result.change_record.from_model_id == "model-a"
        assert result.change_record.to_model_id == "model-b"
        assert result.change_record.trigger_type == FallbackTriggerType.VERIFICATION_FAILURE


# ═══════════════════════════════════════════════════════════════════════
# StageRouter
# ═══════════════════════════════════════════════════════════════════════

class TestStageRouter:

    def setup_method(self) -> None:
        self.sr = StageRouter()

    def test_default_stages(self) -> None:
        stages = self.sr.list_stages()
        assert ExecutionStage.PLANNING in stages
        assert ExecutionStage.SYNTHESIS in stages
        assert len(stages) == 6

    def test_planning_profile(self) -> None:
        assert self.sr.get_model_profile(ExecutionStage.PLANNING) == "reasoning"

    def test_retrieval_profile(self) -> None:
        assert self.sr.get_model_profile(ExecutionStage.RETRIEVAL) == "tool_efficiency"

    def test_synthesis_profile(self) -> None:
        assert self.sr.get_model_profile(ExecutionStage.SYNTHESIS) == "quality"

    def test_verification_profile(self) -> None:
        assert self.sr.get_model_profile(ExecutionStage.VERIFICATION) == "verification"

    def test_needs_route_change(self) -> None:
        assert self.sr.needs_route_change(
            ExecutionStage.PLANNING, ExecutionStage.RETRIEVAL,
        )
        assert not self.sr.needs_route_change(
            ExecutionStage.PLANNING, ExecutionStage.ANALYSIS,
        )  # both "reasoning"

    def test_custom_config(self) -> None:
        config = StageRoutingConfig(
            stages=[
                StageRoutePreference(
                    stage=ExecutionStage.PLANNING,
                    model_profile="custom_reasoning",
                    override_model_id="model-x",
                ),
            ],
        )
        sr = StageRouter(config=config)
        assert sr.get_model_profile(ExecutionStage.PLANNING) == "custom_reasoning"
        assert sr.get_override_model(ExecutionStage.PLANNING) == "model-x"
        assert sr.get_model_profile(ExecutionStage.SYNTHESIS) == "default"

    def test_no_override_by_default(self) -> None:
        assert self.sr.get_override_model(ExecutionStage.PLANNING) is None