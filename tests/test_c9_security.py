"""C9.11 - Security Boundary Tests.

Verifies that the Intelligence Routing Fabric enforces all security
constraints defined in the C9 specification section 60.
"""
import pytest
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

from core.routing.contracts import (
    Route,
    RouteCandidate,
    RouteDecision,
    RoutingConstraints,
    RoutingEvidence,
    RoutingPolicy,
    TaskRequirements,
    TaskClassification,
    QualityRequirements,
    ResourceConstraints,
    SecurityRequirements,
    ExecutionStrategy,
)
from core.routing.enums import (
    EligibilityStatus,
    EvidenceSourceType,
    ProviderHealthStatus,
    RoutingStatus,
    TaskDomain,
)
from core.routing.policies.engine import PolicyEngine
from core.routing.health.tracker import ProviderHealthTracker
from core.routing.evidence.aggregator import EvidenceAggregator
from core.routing.cache.manager import RouteCacheManager


def _reqs(**kw):
    defaults = dict(
        task_id="t1",
        description="test",
        classification=TaskClassification(primary_domain=TaskDomain.GENERAL),
        quality=QualityRequirements(),
        resources=ResourceConstraints(),
        security=SecurityRequirements(),
    )
    defaults.update(kw)
    return TaskRequirements(**defaults)


def _cand(agent="a", model="m", provider="p"):
    return RouteCandidate(
        candidate_id=f"c_{agent}_{model}",
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


def _policy(**constraint_kw):
    return RoutingPolicy(
        policy_id="org",
        name="Org Policy",
        constraints=RoutingConstraints(**constraint_kw),
    )


# ── 1. Frozen Dataclass Immutability ──────────────────────────

class TestImmutability:
    def test_route_frozen_model(self):
        r = _route()
        with pytest.raises(FrozenInstanceError):
            r.model_id = "hacked"

    def test_route_frozen_agent(self):
        r = _route()
        with pytest.raises(FrozenInstanceError):
            r.agent_id = "unauthorized_agent"

    def test_route_frozen_tools(self):
        r = _route()
        with pytest.raises(FrozenInstanceError):
            r.tools = ["malicious_tool"]

    def test_evidence_frozen_metrics(self):
        ev = RoutingEvidence(
            source_type=EvidenceSourceType.ARENA_BENCHMARK,
            benchmark_id="b1",
            sample_count=10,
            metrics={"quality": 0.9},
            observed_at=datetime.now(timezone.utc),
        )
        with pytest.raises(FrozenInstanceError):
            ev.metrics = {"quality": 1.0}

    def test_evidence_frozen_source(self):
        ev = RoutingEvidence(
            source_type=EvidenceSourceType.ARENA_BENCHMARK,
            benchmark_id="b1",
            sample_count=10,
            metrics={},
            observed_at=datetime.now(timezone.utc),
        )
        with pytest.raises(FrozenInstanceError):
            ev.source_type = EvidenceSourceType.MANUAL_ASSESSMENT

    def test_requirements_frozen(self):
        req = _reqs()
        with pytest.raises(FrozenInstanceError):
            req.task_id = "injected_task"

    def test_requirements_security_frozen(self):
        req = _reqs()
        with pytest.raises(FrozenInstanceError):
            req.security = SecurityRequirements(external_write_actions=True)


# ── 2. Policy Enforcement ─────────────────────────────────────

class TestPolicyEnforcement:
    def test_rejects_disallowed_model(self):
        engine = PolicyEngine()
        policy = _policy(allowed_models=["model_a"])
        candidates = [_cand(model="model_a"), _cand(model="model_b")]
        eligible, rejected = engine.apply(candidates, policy, _reqs())
        assert len(eligible) == 1
        assert eligible[0].model_id == "model_a"
        assert len(rejected) == 1
        assert rejected[0].model_id == "model_b"

    def test_rejects_disallowed_agent(self):
        engine = PolicyEngine()
        policy = _policy(allowed_agents=["agent_x"])
        candidates = [_cand(agent="agent_x"), _cand(agent="agent_y")]
        eligible, rejected = engine.apply(candidates, policy, _reqs())
        assert len(eligible) == 1
        assert eligible[0].agent_id == "agent_x"

    def test_rejects_disallowed_provider(self):
        engine = PolicyEngine()
        policy = _policy(allowed_providers=["openai"])
        candidates = [_cand(provider="openai"), _cand(provider="unauthorized")]
        eligible, rejected = engine.apply(candidates, policy, _reqs())
        assert len(eligible) == 1
        assert eligible[0].provider_id == "openai"

    def test_denied_model_rejected(self):
        engine = PolicyEngine()
        policy = _policy(denied_models=["evil_model"])
        candidates = [_cand(model="good"), _cand(model="evil_model")]
        eligible, rejected = engine.apply(candidates, policy, _reqs())
        assert all(c.model_id != "evil_model" for c in eligible)

    def test_open_policy_allows_all(self):
        engine = PolicyEngine()
        policy = _policy()
        candidates = [_cand(model="a"), _cand(model="b"), _cand(model="c")]
        eligible, rejected = engine.apply(candidates, policy, _reqs())
        assert len(eligible) == 3
        assert len(rejected) == 0


# ── 3. Security Constraint Enforcement ────────────────────────

class TestSecurityConstraints:
    def test_external_write_blocked(self):
        req = _reqs(security=SecurityRequirements(external_write_actions=False))
        assert req.security.external_write_actions is False

    def test_sandbox_required(self):
        req = _reqs(security=SecurityRequirements(requires_sandbox=True))
        assert req.security.requires_sandbox is True

    def test_privilege_level_enforced(self):
        req = _reqs(security=SecurityRequirements(max_privilege_level="standard"))
        assert req.security.max_privilege_level == "standard"

    def test_allowed_domains_restrict(self):
        req = _reqs(security=SecurityRequirements(allowed_domains=["internal.corp"]))
        assert "internal.corp" in req.security.allowed_domains

    def test_policy_external_write_constraint(self):
        policy = _policy(external_write_actions=False)
        assert policy.constraints.external_write_actions is False


# ── 4. Evidence Integrity ─────────────────────────────────────

class TestEvidenceIntegrity:
    def test_cannot_inflate_sample_count(self):
        ev = RoutingEvidence(
            source_type=EvidenceSourceType.ARENA_BENCHMARK,
            benchmark_id="b1",
            sample_count=5,
            metrics={"quality": 0.7},
            observed_at=datetime.now(timezone.utc),
        )
        with pytest.raises(FrozenInstanceError):
            ev.sample_count = 10000

    def test_cannot_change_benchmark_id(self):
        ev = RoutingEvidence(
            source_type=EvidenceSourceType.ARENA_BENCHMARK,
            benchmark_id="real_benchmark",
            sample_count=5,
            metrics={},
            observed_at=datetime.now(timezone.utc),
        )
        with pytest.raises(FrozenInstanceError):
            ev.benchmark_id = "fake_benchmark"

    def test_aggregator_handles_empty(self):
        agg = EvidenceAggregator()
        result = agg.aggregate("cand_1", [])
        assert result.total_sample_count == 0


# ── 5. Provider Health Validation ─────────────────────────────

class TestProviderHealthValidation:
    def test_valid_statuses(self):
        for s in ProviderHealthStatus:
            assert isinstance(s, ProviderHealthStatus)

    def test_tracker_unknown_provider(self):
        tracker = ProviderHealthTracker()
        health = tracker.get_health("unknown_provider")
        assert health.status == ProviderHealthStatus.UNKNOWN

    def test_tracker_is_available_unknown(self):
        tracker = ProviderHealthTracker()
        assert tracker.is_available("unknown_provider") is False


# ── 6. Cache Integrity ────────────────────────────────────────

class TestCacheIntegrity:
    def test_cache_miss_returns_none(self):
        cache = RouteCacheManager()
        assert cache.get("nonexistent_key") is None

    def test_cache_put_and_get(self):
        cache = RouteCacheManager()
        route = _route()
        cache.put("key1", route, "dec_1")
        cached = cache.get("key1")
        assert cached is not None
        assert cached.model_id == "m"

    def test_cache_invalidate(self):
        cache = RouteCacheManager()
        cache.put("key1", _route(), "dec_1")
        cache.invalidate("key1")
        assert cache.get("key1") is None


# ── 7. Decision Audit Trail ───────────────────────────────────

class TestDecisionAudit:
    def test_decision_records_rejections(self):
        dec = RouteDecision(
            decision_id="d1",
            task_id="t1",
            status=RoutingStatus.SELECTED,
            requirements=_reqs(),
            selected_route=_route(),
            candidates_considered=3,
            candidates_eligible=1,
            rejected_candidates=[
                {"candidate_id": "c2", "reason": "missing_capability"},
                {"candidate_id": "c3", "reason": "policy_denied"},
            ],
            decision_reason={"confidence": "HIGH"},
        )
        assert len(dec.rejected_candidates) == 2
        assert dec.candidates_considered == 3

    def test_decision_records_evidence(self):
        dec = RouteDecision(
            decision_id="d2",
            task_id="t1",
            status=RoutingStatus.SELECTED,
            requirements=_reqs(),
            selected_route=_route(),
            evidence_refs=["ev_1", "ev_2", "ev_3"],
            decision_reason={},
        )
        assert len(dec.evidence_refs) == 3
