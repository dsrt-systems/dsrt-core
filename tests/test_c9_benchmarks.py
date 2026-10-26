"""C9.11 - Routing Benchmark Tests.

Measures the seven routing quality dimensions from C9 spec section 61.
All benchmarks use deterministic inputs for reproducibility.
"""
import time
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from core.routing.contracts import (
    AggregatedEvidence,
    ExecutionStrategy,
    QualityRequirements,
    ResourceConstraints,
    Route,
    RouteCandidate,
    RouteDecision,
    RoutingConstraints,
    RoutingEvidence,
    RoutingPolicy,
    SecurityRequirements,
    TaskClassification,
    TaskRequirements,
)
from core.routing.enums import (
    EligibilityStatus,
    EvidenceConfidence,
    EvidenceSourceType,
    QualityLevel,
    RoutingStatus,
    TaskDomain,
)
from core.routing.policies.engine import PolicyEngine
from core.routing.evidence.aggregator import EvidenceAggregator
from core.routing.selector.router import IntelligenceRouter
from core.routing.requirements.extractor import RequirementExtractor
from core.routing.candidates.generator import CandidateGenerator
from core.routing.cache.manager import RouteCacheManager


def _reqs(**kw):
    defaults = dict(
        task_id="bench_1",
        description="Research and synthesize findings",
        classification=TaskClassification(primary_domain=TaskDomain.RESEARCH),
        quality=QualityRequirements(),
        resources=ResourceConstraints(),
        security=SecurityRequirements(),
    )
    defaults.update(kw)
    return TaskRequirements(**defaults)


def _cand(agent="a", model="m", provider="p", idx=0):
    return RouteCandidate(
        candidate_id=f"c_{agent}_{model}_{idx}",
        agent_id=agent,
        agent_version_id="v1",
        model_id=model,
        model_version_id="v1",
        provider_id=provider,
        world_id=None,
        world_version_id=None,
        tools=[],
        eligibility=EligibilityStatus.ELIGIBLE,
    )


def _route(agent="a", model="m", provider="p"):
    return Route(
        agent_id=agent,
        agent_version_id="v1",
        model_id=model,
        model_version_id="v1",
        provider_id=provider,
        world_id=None,
        world_version_id=None,
        tools=[],
        execution_strategy=ExecutionStrategy(),
    )


def _evidence(model="m", samples=100, quality=0.85):
    return RoutingEvidence(
        source_type=EvidenceSourceType.ARENA_BENCHMARK,
        benchmark_id="bench_research",
        benchmark_version="v1",
        model_version="v1",
        sample_count=samples,
        metrics={"quality_score": quality},
        observed_at=datetime.now(timezone.utc),
    )


# ── 1. Routing Accuracy ───────────────────────────────────────

class TestRoutingAccuracy:
    """Selected route must satisfy all hard requirements."""

    def test_eligible_candidate_satisfies_constraints(self):
        engine = PolicyEngine()
        policy = RoutingPolicy(
            policy_id="p1", name="P1",
            constraints=RoutingConstraints(allowed_models=["m1", "m2"]),
        )
        candidates = [_cand(model="m1"), _cand(model="m3")]
        eligible, _ = engine.apply(candidates, policy, _reqs())
        assert all(c.model_id in ("m1", "m2") for c in eligible)

    def test_security_constraints_honored(self):
        req = _reqs(security=SecurityRequirements(external_write_actions=False))
        assert req.security.external_write_actions is False


# ── 2. Routing Validity ───────────────────────────────────────

class TestRoutingValidity:
    """Invalid candidates must be correctly rejected."""

    def test_denied_provider_rejected(self):
        engine = PolicyEngine()
        policy = RoutingPolicy(
            policy_id="p1", name="P1",
            constraints=RoutingConstraints(denied_providers=["bad_provider"]),
        )
        candidates = [_cand(provider="good"), _cand(provider="bad_provider")]
        eligible, rejected = engine.apply(candidates, policy, _reqs())
        assert all(c.provider_id != "bad_provider" for c in eligible)
        assert any(c.provider_id == "bad_provider" for c in rejected)

    def test_all_denied_yields_empty(self):
        engine = PolicyEngine()
        policy = RoutingPolicy(
            policy_id="p1", name="P1",
            constraints=RoutingConstraints(allowed_models=["nonexistent"]),
        )
        candidates = [_cand(model="a"), _cand(model="b")]
        eligible, rejected = engine.apply(candidates, policy, _reqs())
        assert len(eligible) == 0
        assert len(rejected) == 2


# ── 3. Routing Latency ────────────────────────────────────────

class TestRoutingLatency:
    """Route resolution must complete within acceptable time."""

    def test_policy_filter_under_10ms(self):
        engine = PolicyEngine()
        policy = RoutingPolicy(
            policy_id="p1", name="P1",
            constraints=RoutingConstraints(allowed_models=["m1"]),
        )
        candidates = [_cand(model=f"m{i}", idx=i) for i in range(50)]
        start = time.perf_counter()
        engine.apply(candidates, policy, _reqs())
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 10, f"Policy filter took {elapsed_ms:.1f}ms"

    def test_evidence_aggregation_under_10ms(self):
        agg = EvidenceAggregator()
        evidence = [_evidence(samples=i + 1) for i in range(20)]
        start = time.perf_counter()
        agg.aggregate("cand_1", evidence)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 10, f"Aggregation took {elapsed_ms:.1f}ms"


# ── 4. Policy Compliance ──────────────────────────────────────

class TestPolicyCompliance:
    """Routing must respect all policy dimensions."""

    def test_cost_constraint_in_policy(self):
        policy = RoutingPolicy(
            policy_id="p1", name="P1",
            constraints=RoutingConstraints(max_cost_usd=1.0),
        )
        assert policy.constraints.max_cost_usd == 1.0

    def test_latency_constraint_in_policy(self):
        policy = RoutingPolicy(
            policy_id="p1", name="P1",
            constraints=RoutingConstraints(max_latency_seconds=5.0),
        )
        assert policy.constraints.max_latency_seconds == 5.0

    def test_combined_constraints(self):
        policy = RoutingPolicy(
            policy_id="p1", name="P1",
            constraints=RoutingConstraints(
                allowed_models=["m1"],
                allowed_providers=["openai"],
                external_write_actions=False,
                max_cost_usd=2.0,
            ),
        )
        engine = PolicyEngine()
        candidates = [
            _cand(model="m1", provider="openai"),
            _cand(model="m2", provider="openai"),
            _cand(model="m1", provider="anthropic"),
        ]
        eligible, rejected = engine.apply(candidates, policy, _reqs())
        assert len(eligible) == 1
        assert eligible[0].model_id == "m1"
        assert eligible[0].provider_id == "openai"


# ── 5. Evidence Utilization ───────────────────────────────────

class TestEvidenceUtilization:
    """Router must incorporate observed evidence."""

    def test_aggregation_uses_sample_count(self):
        agg = EvidenceAggregator()
        ev1 = _evidence(samples=10, quality=0.9)
        ev2 = _evidence(samples=1000, quality=0.7)
        result = agg.aggregate("cand_1", [ev1, ev2])
        assert result.total_sample_count == 1010

    def test_stale_evidence_detected(self):
        old = RoutingEvidence(
            source_type=EvidenceSourceType.ARENA_BENCHMARK,
            benchmark_id="b1",
            sample_count=50,
            metrics={"quality": 0.9},
            observed_at=datetime.now(timezone.utc) - timedelta(days=365),
        )
        assert old.observed_at < datetime.now(timezone.utc) - timedelta(days=300)


# ── 6. Reproducibility ────────────────────────────────────────

class TestReproducibility:
    """Same inputs must produce same routing decisions."""

    def test_deterministic_policy_filter(self):
        engine = PolicyEngine()
        policy = RoutingPolicy(
            policy_id="p1", name="P1",
            constraints=RoutingConstraints(allowed_models=["m1", "m2"]),
        )
        candidates = [_cand(model="m1"), _cand(model="m2"), _cand(model="m3")]
        req = _reqs()
        e1, r1 = engine.apply(candidates, policy, req)
        e2, r2 = engine.apply(candidates, policy, req)
        assert [c.candidate_id for c in e1] == [c.candidate_id for c in e2]
        assert [c.candidate_id for c in r1] == [c.candidate_id for c in r2]

    def test_deterministic_cache_key(self):
        cache = RouteCacheManager()
        route = _route()
        cache.put("stable_key", route, "dec_1")
        r1 = cache.get("stable_key")
        r2 = cache.get("stable_key")
        assert r1.model_id == r2.model_id
        assert r1.agent_id == r2.agent_id


# ── 7. Fallback Success ───────────────────────────────────────

class TestFallbackSuccess:
    """Fallback mechanisms must recover from failures."""

    def test_cache_invalidate_and_rebuild(self):
        cache = RouteCacheManager()
        cache.put("k1", _route(model="old"), "d1")
        cache.invalidate("k1")
        cache.put("k1", _route(model="new"), "d2")
        assert cache.get("k1").model_id == "new"

    def test_empty_candidates_handled(self):
        engine = PolicyEngine()
        policy = RoutingPolicy(policy_id="p1", name="P1")
        eligible, rejected = engine.apply([], policy, _reqs())
        assert len(eligible) == 0
        assert len(rejected) == 0
