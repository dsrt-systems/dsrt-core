# tests/test_c9_sdk_events.py
"""
C9.9 SDK, Events & API Integration — comprehensive tests.

Covers:
  - RoutingEventEmitter (§48)
  - RoutingSDK (§53–54)
"""

from __future__ import annotations

import pytest

from core.routing.contracts import (
    AggregatedEvidence,
    RouteCandidate,
    RoutingPolicy,
    RoutingProfile,
    TaskClassification,
    TaskRequirements,
)
from core.routing.enums import (
    EvidenceConfidence,
    ExecutionStage,
    RejectionCategory,
    RoutingPriority,
    RoutingStatus,
    TaskDomain,
)
from core.routing.events import RoutingEventType
from core.routing.events import RoutingEvent, RoutingEventEmitter
from core.routing.selector.router import IntelligenceRouter
from sdk.routing.client import RoutingSDK


# ── Helpers ────────────────────────────────────────────────────────────

def _requirements(task_id: str = "task-1") -> TaskRequirements:
    return TaskRequirements(
        task_id=task_id,
        description="Research task",
        classification=TaskClassification(primary_domain=TaskDomain.RESEARCH),
    )


def _candidate(
    cid: str = "cand-1",
    model: str = "model-a",
    eligible: bool = True,
) -> RouteCandidate:
    c = RouteCandidate(
        candidate_id=cid,
        agent_id="agent-1",
        agent_version_id="av-1",
        model_id=model,
        model_version_id="mv-1",
        provider_id="prov-1",
    )
    if not eligible:
        c.reject(RejectionCategory.MISSING_CAPABILITY, "no vision")
    return c


def _evidence(cid: str = "cand-1") -> AggregatedEvidence:
    return AggregatedEvidence(
        candidate_key=cid,
        aggregated_metrics={"quality": 0.9, "reliability": 0.85},
        total_sample_count=100,
        freshness_weight=0.95,
        confidence=EvidenceConfidence.HIGH,
    )


# ═══════════════════════════════════════════════════════════════════════
# RoutingEventEmitter
# ═══════════════════════════════════════════════════════════════════════

class TestRoutingEventEmitter:

    def setup_method(self) -> None:
        self.emitter = RoutingEventEmitter()

    def test_emit_basic(self) -> None:
        ev = self.emitter.emit(
            RoutingEventType.ROUTING_STARTED, "task-1",
        )
        assert ev.event_type == RoutingEventType.ROUTING_STARTED
        assert ev.task_id == "task-1"
        assert len(self.emitter.events) == 1

    def test_emit_with_payload(self) -> None:
        ev = self.emitter.emit(
            RoutingEventType.ROUTE_SELECTED,
            "task-1", "dec-1",
            model_id="model-a", score=0.95,
        )
        assert ev.payload["model_id"] == "model-a"
        assert ev.payload["score"] == 0.95

    def test_all_convenience_methods(self) -> None:
        self.emitter.routing_started("t1")
        self.emitter.requirements_extracted("t1")
        self.emitter.candidates_generated("t1", "d1", count=5)
        self.emitter.candidate_rejected("t1", "d1", "c1", "no cap")
        self.emitter.route_evaluated("t1", "d1")
        self.emitter.route_selected("t1", "d1", model_id="m1")
        self.emitter.route_started("t1", "d1")
        self.emitter.route_changed("t1", "d1", "m1", "m2", "timeout")
        self.emitter.fallback_triggered("t1", "d1", trigger="timeout")
        self.emitter.model_switched("t1", "d1", "m1", "m2")
        self.emitter.agent_switched("t1", "d1", "a1", "a2")
        self.emitter.routing_completed("t1", "d1")
        self.emitter.routing_failed("t1", "d1", reason="no candidates")
        assert len(self.emitter.events) == 13

    def test_events_for_task(self) -> None:
        self.emitter.routing_started("t1")
        self.emitter.routing_started("t2")
        self.emitter.routing_completed("t1", "d1")
        assert len(self.emitter.events_for_task("t1")) == 2
        assert len(self.emitter.events_for_task("t2")) == 1

    def test_events_of_type(self) -> None:
        self.emitter.routing_started("t1")
        self.emitter.routing_started("t2")
        self.emitter.routing_completed("t1", "d1")
        started = self.emitter.events_of_type(
            RoutingEventType.ROUTING_STARTED,
        )
        assert len(started) == 2

    def test_clear(self) -> None:
        self.emitter.routing_started("t1")
        self.emitter.routing_started("t2")
        assert self.emitter.clear() == 2
        assert len(self.emitter.events) == 0

    def test_listener_called(self) -> None:
        received: list[RoutingEvent] = []
        emitter = RoutingEventEmitter(listeners=[received.append])
        emitter.routing_started("t1")
        assert len(received) == 1

    def test_listener_exception_ignored(self) -> None:
        def bad_listener(ev: RoutingEvent) -> None:
            raise RuntimeError("boom")

        emitter = RoutingEventEmitter(listeners=[bad_listener])
        ev = emitter.routing_started("t1")
        assert ev is not None  # pipeline not broken

    def test_all_event_types_exist(self) -> None:
        expected = {
            "ROUTING_STARTED", "REQUIREMENTS_EXTRACTED",
            "CANDIDATES_GENERATED", "CANDIDATE_REJECTED",
            "ROUTE_EVALUATED", "ROUTE_SELECTED",
            "ROUTE_STARTED", "ROUTE_CHANGED",
            "FALLBACK_TRIGGERED", "MODEL_SWITCHED",
            "AGENT_SWITCHED", "ROUTING_COMPLETED",
            "ROUTING_FAILED",
        }
        actual = {e.value for e in RoutingEventType}
        assert expected == actual


# ═══════════════════════════════════════════════════════════════════════
# RoutingSDK
# ═══════════════════════════════════════════════════════════════════════

class TestRoutingSDK:

    def setup_method(self) -> None:
        self.router = IntelligenceRouter()
        self.emitter = RoutingEventEmitter()
        self.sdk = RoutingSDK(
            router=self.router,
            event_emitter=self.emitter,
        )

    def test_resolve_basic(self) -> None:
        req = _requirements()
        candidates = [_candidate("c1")]
        ev_map = {"c1": _evidence("c1")}
        decision = self.sdk.resolve(req, candidates, evidence_map=ev_map)
        assert decision.status == RoutingStatus.SELECTED
        assert decision.selected_route is not None

    def test_resolve_emits_events(self) -> None:
        req = _requirements()
        candidates = [_candidate("c1")]
        self.sdk.resolve(req, candidates)
        events = self.emitter.events
        types = [e.event_type for e in events]
        assert RoutingEventType.ROUTING_STARTED in types
        assert RoutingEventType.REQUIREMENTS_EXTRACTED in types
        assert RoutingEventType.CANDIDATES_GENERATED in types
        assert RoutingEventType.ROUTE_SELECTED in types
        assert RoutingEventType.ROUTING_COMPLETED in types

    def test_resolve_failure_emits_event(self) -> None:
        req = _requirements()
        candidates = [_candidate("c1", eligible=False)]
        self.sdk.resolve(req, candidates)
        types = [e.event_type for e in self.emitter.events]
        assert RoutingEventType.ROUTING_FAILED in types

    def test_resolve_rejection_events(self) -> None:
        req = _requirements()
        candidates = [
            _candidate("c1", eligible=False),
            _candidate("c2"),
        ]
        self.sdk.resolve(req, candidates)
        rejected = self.emitter.events_of_type(
            RoutingEventType.CANDIDATE_REJECTED,
        )
        assert len(rejected) == 1
        assert rejected[0].payload["candidate_id"] == "c1"

    def test_resolve_with_policy_and_profile(self) -> None:
        req = _requirements()
        candidates = [_candidate("c1")]
        pol = RoutingPolicy(policy_id="pol-1", name="Test")
        prof = RoutingProfile(
            profile_id="prof-1", name="Quality",
            quality_priority=RoutingPriority.HIGH,
        )
        decision = self.sdk.resolve(
            req, candidates, policy=pol, profile=prof,
        )
        assert decision.routing_policy_id == "pol-1"
        assert decision.routing_profile_id == "prof-1"

    def test_resolve_stage(self) -> None:
        req = _requirements()
        candidates = [_candidate("c1")]
        decision = self.sdk.resolve_stage(
            req, candidates, stage=ExecutionStage.VERIFICATION,
        )
        assert decision.status == RoutingStatus.SELECTED
        # Check stage event was emitted
        eval_events = self.emitter.events_of_type(
            RoutingEventType.ROUTE_EVALUATED,
        )
        assert len(eval_events) >= 1
        assert eval_events[0].payload.get("stage") == "VERIFICATION"

    def test_validate_agent_request_clean(self) -> None:
        req = _requirements()
        errors = self.sdk.validate_agent_request(req)
        assert errors == []

    def test_validate_agent_forced_model(self) -> None:
        req = TaskRequirements(
            task_id="t1",
            description="test",
            metadata={"forced_model": "gpt-4o"},
        )
        pol = RoutingPolicy(policy_id="pol-1", name="Strict")
        errors = self.sdk.validate_agent_request(req, policy=pol)
        assert len(errors) >= 1
        assert "model" in errors[0].lower()

    def test_validate_agent_forced_provider(self) -> None:
        req = TaskRequirements(
            task_id="t1",
            description="test",
            metadata={"forced_provider": "openai"},
        )
        pol = RoutingPolicy(policy_id="pol-1", name="Strict")
        errors = self.sdk.validate_agent_request(req, policy=pol)
        assert len(errors) >= 1
        assert "provider" in errors[0].lower()

    def test_empty_task_id_raises(self) -> None:
        with pytest.raises(ValueError, match="task_id"):
            TaskRequirements(task_id="", description="test")

    def test_events_property(self) -> None:
        assert self.sdk.events is self.emitter