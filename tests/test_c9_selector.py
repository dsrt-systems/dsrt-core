# tests/test_c9_selector.py
"""
C9.5 Route Selector & Decision Engine — comprehensive tests.

Covers:
  - RouteEvaluator (multi-dimensional scoring)
  - RouteSelector (weighted selection, ranking, tie-breaking)
  - DecisionExplainer (structured explanations)
  - IntelligenceRouter (full pipeline orchestration)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.routing.contracts import (
    AggregatedEvidence,
    CandidateRejection,
    Route,
    RouteCandidate,
    RouteDecision,
    RouteEvaluation,
    RoutingConstraints,
    RoutingPolicy,
    RoutingPreferences,
    RoutingProfile,
    TaskClassification,
    TaskRequirements,
)
from core.routing.enums import (
    EligibilityStatus,
    EvidenceConfidence,
    EvidenceSourceType,
    RejectionCategory,
    RoutingPriority,
    RoutingStatus,
    TaskDomain,
)
from core.routing.selector.evaluator import RouteEvaluator
from core.routing.selector.explainer import DecisionExplainer
from core.routing.selector.router import IntelligenceRouter
from core.routing.selector.selector import RouteSelector


# ── Helpers ────────────────────────────────────────────────────────────

NOW = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


def _candidate(
    cid: str = "cand-1",
    model: str = "model-a",
    model_ver: str = "mv-1",
    agent: str = "agent-1",
    agent_ver: str = "av-1",
    provider: str = "prov-1",
    eligible: bool = True,
) -> RouteCandidate:
    c = RouteCandidate(
        candidate_id=cid,
        agent_id=agent,
        agent_version_id=agent_ver,
        model_id=model,
        model_version_id=model_ver,
        provider_id=provider,
    )
    if not eligible:
        c.reject(RejectionCategory.MISSING_CAPABILITY, "no vision")
    return c


def _evidence(
    candidate_key: str = "cand-1",
    quality: float = 0.85,
    reliability: float = 0.9,
    latency: float = 0.2,
    cost: float = 0.1,
    samples: int = 100,
    confidence: EvidenceConfidence = EvidenceConfidence.HIGH,
) -> AggregatedEvidence:
    return AggregatedEvidence(
        candidate_key=candidate_key,
        aggregated_metrics={
            "quality": quality,
            "reliability": reliability,
            "latency": latency,
            "cost": cost,
        },
        total_sample_count=samples,
        freshness_weight=0.95,
        confidence=confidence,
    )


def _requirements(
    task_id: str = "task-1",
    desc: str = "Research task",
) -> TaskRequirements:
    return TaskRequirements(
        task_id=task_id,
        description=desc,
        classification=TaskClassification(primary_domain=TaskDomain.RESEARCH),
    )


def _policy() -> RoutingPolicy:
    return RoutingPolicy(
        policy_id="pol-1",
        name="Test Policy",
        preferences=RoutingPreferences(
            quality_priority=RoutingPriority.HIGH,
            cost_priority=RoutingPriority.MEDIUM,
        ),
    )


def _profile() -> RoutingProfile:
    return RoutingProfile(
        profile_id="prof-quality",
        name="Quality",
        quality_priority=RoutingPriority.HIGH,
        reliability_priority=RoutingPriority.HIGH,
        cost_priority=RoutingPriority.LOW,
        latency_priority=RoutingPriority.LOW,
    )


# ═══════════════════════════════════════════════════════════════════════
# RouteEvaluator
# ═══════════════════════════════════════════════════════════════════════

class TestRouteEvaluator:

    def setup_method(self) -> None:
        self.ev = RouteEvaluator()

    def test_evaluate_with_evidence(self) -> None:
        c = _candidate()
        ev = _evidence()
        result = self.ev.evaluate(c, ev)
        assert result.candidate_id == "cand-1"
        assert result.quality_score > 0.5
        assert result.reliability_score > 0.5
        assert result.latency_score > 0.5  # inverted: 1 - 0.2 = 0.8
        assert result.cost_score > 0.5     # inverted: 1 - 0.1 = 0.9

    def test_evaluate_without_evidence(self) -> None:
        c = _candidate()
        result = self.ev.evaluate(c, None)
        # Default score = 0.5, minus uncertainty penalty
        assert result.quality_score < 0.5
        assert result.reliability_score < 0.5

    def test_evaluate_low_confidence_penalty(self) -> None:
        c = _candidate()
        high = _evidence(confidence=EvidenceConfidence.HIGH)
        low = _evidence(confidence=EvidenceConfidence.LOW)
        r_high = self.ev.evaluate(c, high)
        r_low = self.ev.evaluate(c, low)
        assert r_high.quality_score > r_low.quality_score

    def test_evaluate_insufficient_confidence(self) -> None:
        c = _candidate()
        ev = _evidence(confidence=EvidenceConfidence.INSUFFICIENT)
        r = self.ev.evaluate(c, ev)
        assert r.uncertainty["confidence"] == "INSUFFICIENT"
        assert r.uncertainty["penalty"] == 0.5

    def test_evaluate_preserves_constraint_fit(self) -> None:
        c = _candidate()
        c.constraint_fit = {"budget": True, "latency": True}
        r = self.ev.evaluate(c, _evidence())
        assert r.constraint_fit == {"budget": True, "latency": True}

    def test_evaluate_all(self) -> None:
        c1 = _candidate("c1")
        c2 = _candidate("c2", model="model-b")
        ev_map = {
            "c1": _evidence("c1", quality=0.9),
            "c2": _evidence("c2", quality=0.7),
        }
        results = self.ev.evaluate_all([c1, c2], ev_map)
        assert len(results) == 2
        assert results[0].quality_score > results[1].quality_score

    def test_evaluate_all_empty(self) -> None:
        results = self.ev.evaluate_all([], {})
        assert results == []

    def test_custom_metric_mapping(self) -> None:
        ev = RouteEvaluator(
            metric_mapping={"quality": ["my_score"]},
        )
        c = _candidate()
        agg = AggregatedEvidence(
            candidate_key="c1",
            aggregated_metrics={"my_score": 0.95},
            total_sample_count=50,
            freshness_weight=1.0,
            confidence=EvidenceConfidence.HIGH,
        )
        r = ev.evaluate(c, agg)
        assert r.quality_score > 0.8

    def test_non_numeric_metrics_ignored(self) -> None:
        c = _candidate()
        agg = AggregatedEvidence(
            candidate_key="c1",
            aggregated_metrics={
                "quality": 0.8,
                "notes": "good run",
                "quality_consensus": "STRONG_PASS",
            },
            total_sample_count=50,
            freshness_weight=1.0,
            confidence=EvidenceConfidence.HIGH,
        )
        r = self.ev.evaluate(c, agg)
        assert r.quality_score > 0.5

    def test_weighted_score(self) -> None:
        c = _candidate()
        ev = _evidence(quality=0.9, reliability=0.8)
        r = self.ev.evaluate(c, ev)
        weights = {"quality": 3.0, "reliability": 1.0, "latency": 0.0, "cost": 0.0}
        ws = r.weighted_score(weights)
        assert ws > 0.0


# ═══════════════════════════════════════════════════════════════════════
# RouteSelector
# ═══════════════════════════════════════════════════════════════════════

class TestRouteSelector:

    def setup_method(self) -> None:
        self.sel = RouteSelector()
        self.weights = {
            "quality": 2.0, "reliability": 2.0,
            "latency": 1.0, "cost": 1.0,
        }

    def _eval(self, cid: str, q: float, r: float) -> RouteEvaluation:
        return RouteEvaluation(
            candidate_id=cid,
            quality_score=q,
            reliability_score=r,
            latency_score=0.5,
            cost_score=0.5,
        )

    def test_select_best(self) -> None:
        evals = [
            self._eval("c1", 0.6, 0.6),
            self._eval("c2", 0.9, 0.9),
            self._eval("c3", 0.7, 0.7),
        ]
        best = self.sel.select(evals, self.weights)
        assert best is not None
        assert best.candidate_id == "c2"

    def test_select_empty(self) -> None:
        assert self.sel.select([], self.weights) is None

    def test_rank_order(self) -> None:
        evals = [
            self._eval("c1", 0.5, 0.5),
            self._eval("c2", 0.9, 0.9),
            self._eval("c3", 0.7, 0.7),
        ]
        ranked = self.sel.rank(evals, self.weights)
        assert ranked[0].candidate_id == "c2"
        assert ranked[1].candidate_id == "c3"
        assert ranked[2].candidate_id == "c1"

    def test_tie_break_by_candidate_id(self) -> None:
        evals = [
            self._eval("c-b", 0.8, 0.8),
            self._eval("c-a", 0.8, 0.8),
        ]
        ranked = self.sel.rank(evals, self.weights)
        assert ranked[0].candidate_id == "c-a"  # lexicographic

    def test_select_top_n(self) -> None:
        evals = [self._eval(f"c{i}", 0.5 + i * 0.1, 0.5) for i in range(5)]
        top = self.sel.select_top_n(evals, self.weights, n=2)
        assert len(top) == 2
        assert top[0].candidate_id == "c4"

    def test_select_top_n_clamp(self) -> None:
        evals = [self._eval("c1", 0.8, 0.8)]
        top = self.sel.select_top_n(evals, self.weights, n=0)
        assert len(top) == 1  # clamped to 1

    def test_deterministic(self) -> None:
        evals = [
            self._eval("c1", 0.7, 0.8),
            self._eval("c2", 0.8, 0.7),
        ]
        r1 = self.sel.select(evals, self.weights)
        r2 = self.sel.select(evals, self.weights)
        assert r1.candidate_id == r2.candidate_id


# ═══════════════════════════════════════════════════════════════════════
# DecisionExplainer
# ═══════════════════════════════════════════════════════════════════════

class TestDecisionExplainer:

    def setup_method(self) -> None:
        self.explainer = DecisionExplainer()

    def _make_decision(
        self,
        selected: bool = True,
        with_req: bool = True,
    ) -> RouteDecision:
        d = RouteDecision(
            decision_id="dec-1",
            task_id="task-1",
            status=RoutingStatus.SELECTED if selected else RoutingStatus.FAILED,
            requirements=_requirements() if with_req else None,
            routing_policy_id="pol-1",
            routing_policy_version="1",
            routing_profile_id="prof-1",
            candidates_considered=5,
            candidates_eligible=3,
            rejected_candidates=[
                {"candidate_id": "c4", "category": "BUDGET_EXCEEDED", "detail": "too expensive"},
            ],
            evidence_refs=["bench-1:model-a"],
            decision_reason={"selected_candidate": "c1", "weighted_score": 0.85},
        )
        if selected:
            d.selected_route = Route(
                agent_id="agent-1",
                agent_version_id="av-1",
                model_id="model-a",
                model_version_id="mv-1",
                provider_id="prov-1",
                tools=["web.search"],
            )
        return d

    def test_explain_selected(self) -> None:
        d = self._make_decision()
        exp = self.explainer.explain(d)
        assert exp["decision_id"] == "dec-1"
        assert exp["status"] == "SELECTED"
        assert "selected" in exp
        assert exp["selected"]["model"] == "model-a@mv-1"
        assert exp["candidates"]["considered"] == 5
        assert "BUDGET_EXCEEDED" in exp["rejection_summary"]

    def test_explain_failed(self) -> None:
        d = self._make_decision(selected=False)
        exp = self.explainer.explain(d)
        assert exp["status"] == "FAILED"
        assert "selected" not in exp

    def test_explain_with_evaluations(self) -> None:
        d = self._make_decision()
        evals = [
            RouteEvaluation(candidate_id="c1", quality_score=0.9),
            RouteEvaluation(candidate_id="c2", quality_score=0.7),
        ]
        exp = self.explainer.explain(d, evals)
        assert "top_evaluations" in exp
        assert len(exp["top_evaluations"]) == 2

    def test_explain_text(self) -> None:
        d = self._make_decision()
        text = self.explainer.explain_text(d)
        assert "Route Decision dec-1" in text
        assert "SELECTED" in text
        assert "model-a" in text

    def test_explain_no_requirements(self) -> None:
        d = self._make_decision(with_req=False)
        exp = self.explainer.explain(d)
        assert "required" not in exp

    def test_explain_evidence_refs(self) -> None:
        d = self._make_decision()
        exp = self.explainer.explain(d)
        assert "bench-1:model-a" in exp["evidence_refs"]


# ═══════════════════════════════════════════════════════════════════════
# IntelligenceRouter
# ═══════════════════════════════════════════════════════════════════════

class TestIntelligenceRouter:

    def setup_method(self) -> None:
        self.router = IntelligenceRouter()

    def test_route_basic(self) -> None:
        req = _requirements()
        candidates = [
            _candidate("c1", model="model-a"),
            _candidate("c2", model="model-b"),
        ]
        ev_map = {
            "c1": _evidence("c1", quality=0.9, reliability=0.85),
            "c2": _evidence("c2", quality=0.7, reliability=0.6),
        }
        decision = self.router.route(req, candidates, evidence_map=ev_map)
        assert decision.status == RoutingStatus.SELECTED
        assert decision.selected_route is not None
        assert decision.selected_route.model_id == "model-a"
        assert decision.candidates_considered == 2
        assert decision.candidates_eligible == 2

    def test_route_with_policy_and_profile(self) -> None:
        req = _requirements()
        candidates = [_candidate("c1")]
        ev_map = {"c1": _evidence("c1")}
        decision = self.router.route(
            req, candidates,
            policy=_policy(),
            profile=_profile(),
            evidence_map=ev_map,
        )
        assert decision.routing_policy_id == "pol-1"
        assert decision.routing_profile_id == "prof-quality"

    def test_route_all_rejected(self) -> None:
        req = _requirements()
        candidates = [
            _candidate("c1", eligible=False),
            _candidate("c2", eligible=False),
        ]
        decision = self.router.route(req, candidates)
        assert decision.status == RoutingStatus.FAILED
        assert decision.selected_route is None
        assert "no_eligible" in decision.decision_reason["reason"]

    def test_route_mixed_eligibility(self) -> None:
        req = _requirements()
        candidates = [
            _candidate("c1", eligible=False),
            _candidate("c2", model="model-b"),
        ]
        ev_map = {"c2": _evidence("c2")}
        decision = self.router.route(req, candidates, evidence_map=ev_map)
        assert decision.status == RoutingStatus.SELECTED
        assert decision.selected_route.model_id == "model-b"
        assert decision.candidates_eligible == 1
        assert len(decision.rejected_candidates) == 1

    def test_route_no_evidence(self) -> None:
        req = _requirements()
        candidates = [_candidate("c1")]
        decision = self.router.route(req, candidates)
        assert decision.status == RoutingStatus.SELECTED
        # Should still select even without evidence (default scores)

    def test_route_configuration_hash(self) -> None:
        req = _requirements()
        candidates = [_candidate("c1")]
        ev_map = {"c1": _evidence("c1")}
        d1 = self.router.route(req, candidates, evidence_map=ev_map)
        d2 = self.router.route(req, candidates, evidence_map=ev_map)
        assert d1.configuration_hash == d2.configuration_hash
        assert len(d1.configuration_hash) == 16

    def test_route_evidence_refs_populated(self) -> None:
        req = _requirements()
        candidates = [_candidate("c1")]
        from core.routing.contracts import RoutingEvidence
        ev = AggregatedEvidence(
            candidate_key="c1",
            sources=[
                RoutingEvidence(
                    source_type=EvidenceSourceType.ARENA_BENCHMARK,
                    benchmark_id="bench-1",
                    model_version="mv-1",
                    sample_count=50,
                ),
            ],
            aggregated_metrics={"quality": 0.9},
            total_sample_count=50,
            freshness_weight=1.0,
            confidence=EvidenceConfidence.HIGH,
        )
        decision = self.router.route(req, candidates, evidence_map={"c1": ev})
        assert "bench-1:mv-1" in decision.evidence_refs

    def test_route_decision_reason_complete(self) -> None:
        req = _requirements()
        candidates = [_candidate("c1")]
        ev_map = {"c1": _evidence("c1")}
        decision = self.router.route(req, candidates, evidence_map=ev_map)
        reason = decision.decision_reason
        assert "selected_candidate" in reason
        assert "quality_score" in reason
        assert "weighted_score" in reason
        assert "confidence" in reason
        assert "explanation" in reason

    def test_route_empty_candidates(self) -> None:
        req = _requirements()
        decision = self.router.route(req, [])
        assert decision.status == RoutingStatus.FAILED

    def test_route_preserves_requirements(self) -> None:
        req = _requirements("task-42", "Special task")
        candidates = [_candidate("c1")]
        decision = self.router.route(req, candidates)
        assert decision.requirements is not None
        assert decision.requirements.task_id == "task-42"

    def test_route_selected_route_fields(self) -> None:
        req = _requirements()
        c = _candidate("c1", model="gpt-4o", model_ver="v2",
                       agent="research", agent_ver="v3",
                       provider="openai")
        c.world_id = "research-world"
        c.world_version_id = "wv-1"
        c.tools = ["web.search", "pdf.extract"]
        decision = self.router.route(req, [c])
        r = decision.selected_route
        assert r.model_id == "gpt-4o"
        assert r.model_version_id == "v2"
        assert r.agent_id == "research"
        assert r.provider_id == "openai"
        assert r.world_id == "research-world"
        assert r.tools == ["web.search", "pdf.extract"]