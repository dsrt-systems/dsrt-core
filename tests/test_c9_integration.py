"""C9.10 - Cross-Phase Integration Tests."""
import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone, timedelta

from core.routing.contracts import (
    AggregatedEvidence,
    QualityRequirements,
    ResourceConstraints,
    Route,
    RouteCandidate,
    RouteDecision,
    RoutingPolicy,
    SecurityRequirements,
    TaskClassification,
    TaskRequirements,
)
from core.routing.enums import (
    EvidenceConfidence,
    EvidenceSourceType,
    ExecutionStage,
    QualityLevel,
    RoutingStatus,
    TaskDomain,
)
from core.routing.integrations.arena_bridge import ArenaEvidenceBridge
from core.routing.integrations.orchestration_hook import OrchestrationRoutingHook
from core.routing.integrations.verification_hook import VerificationRoutingHook, VerificationConfig
from core.routing.integrations.kernel_hook import KernelRoutingHook
from core.routing.integrations.golden_scenario import GoldenScenarioRunner, GoldenScenarioResult


def _run(status="COMPLETED", agent="researcher-v2", model="gpt-4-turbo", metrics=None, **kw):
    d = {
        "id": kw.get("id", "run_001"), "status": status,
        "agent_slug": agent, "agent_version": "2.1",
        "model_slug": model, "model_version": "2024-01",
        "provider_id": "openai", "world_slug": "research-lab",
        "world_version": "1.0", "configuration_hash": "abc123",
        "repetition": 1,
        "created_at": datetime.now(timezone.utc) - timedelta(hours=24),
        "completed_at": datetime.now(timezone.utc) - timedelta(hours=23),
        "metrics": metrics if metrics is not None else {"task_success": 0.92, "latency_ms": 1200, "cost_usd": 0.05, "reliability": 0.95, "total_tokens": 4500},
        "metadata_json": kw.get("metadata", {}),
    }
    d.update(kw)
    return d


def _reqs(**kw):
    d = {"task_id": "task_001", "description": "Research this topic and produce a verified report"}
    d.update(kw)
    return TaskRequirements(**d)


def _cand(aid="agent-a", mid="model-x", **kw):
    d = {"candidate_id": f"cand_{aid}_{mid}", "agent_id": aid, "agent_version_id": "v1",
         "model_id": mid, "model_version_id": "v1", "provider_id": "openai"}
    d.update(kw)
    return RouteCandidate(**d)


def _route(**kw):
    d = {"agent_id": "agent-a", "agent_version_id": "v1", "model_id": "model-x",
         "model_version_id": "v1", "provider_id": "openai"}
    d.update(kw)
    return Route(**d)


def _dec(**kw):
    d = {"decision_id": "dec_001", "task_id": "task_001", "status": RoutingStatus.SELECTED,
         "requirements": _reqs(), "selected_route": _route(),
         "candidates_considered": 5, "candidates_eligible": 3,
         "decision_reason": {"selected_candidate": "cand_agent-a_model-x", "confidence": "HIGH"}}
    d.update(kw)
    return RouteDecision(**d)


# ── Arena Bridge ──────────────────────────────────────────────

class TestArenaBridge:
    def setup_method(self):
        self.b = ArenaEvidenceBridge()

    def test_completed_run(self):
        ev = self.b.transform_run_to_evidence(_run())
        assert ev is not None
        assert ev.source_type == EvidenceSourceType.ARENA_BENCHMARK
        assert ev.metrics["quality_score"] == 0.92
        assert ev.metrics["latency_ms"] == 1200.0

    def test_full_metrics(self):
        ev = self.b.transform_run_to_evidence(_run(metrics={"accuracy": 0.95, "p50_latency_ms": 800, "total_cost": 0.03, "success_rate": 0.98, "token_count": 6000}))
        assert ev.metrics["quality_score"] == 0.95
        assert ev.metrics["reliability_score"] == 0.98

    def test_empty_metrics(self):
        ev = self.b.transform_run_to_evidence(_run(metrics={}))
        assert ev.metrics["quality_score"] == 0.0

    def test_failed_returns_none(self):
        assert self.b.transform_run_to_evidence(_run(status="FAILED")) is None

    def test_cancelled_returns_none(self):
        assert self.b.transform_run_to_evidence(_run(status="CANCELLED")) is None

    def test_running_returns_none(self):
        assert self.b.transform_run_to_evidence(_run(status="RUNNING")) is None

    def test_no_agent_no_model(self):
        r = _run(); r["agent_slug"] = None; r["model_slug"] = None
        assert self.b.transform_run_to_evidence(r) is None

    def test_batch_filters(self):
        runs = [_run(id="r1"), _run(id="r2", status="FAILED"), _run(id="r3"), _run(id="r4", status="RUNNING")]
        assert len(self.b.transform_runs_batch(runs)) == 2

    def test_experiment_source(self):
        ev = self.b.transform_run_to_evidence(_run(experiment_id="exp_1"))
        assert ev.source_type == EvidenceSourceType.ARENA_EXPERIMENT

    def test_benchmark_source(self):
        ev = self.b.transform_run_to_evidence(_run(benchmark_id="b1"))
        assert ev.source_type == EvidenceSourceType.ARENA_BENCHMARK
        assert ev.benchmark_id == "b1"

    def test_provider_in_metrics(self):
        ev = self.b.transform_run_to_evidence(_run())
        assert ev.metrics["provider_id"] == "openai"

    def test_observed_at(self):
        ts = datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)
        ev = self.b.transform_run_to_evidence(_run(completed_at=ts))
        assert ev.observed_at == ts

    def test_sample_count(self):
        assert self.b.transform_run_to_evidence(_run()).sample_count == 1


# ── Orchestration Hook ────────────────────────────────────────

class TestOrchestrationHook:
    def setup_method(self):
        self.router = MagicMock()
        self.router.route.return_value = _dec()
        self.hook = OrchestrationRoutingHook(router=self.router)

    def test_get_route(self):
        d = self.hook.get_route_for_task("Summarize article", candidates=[_cand()])
        assert d.decision_id == "dec_001"
        self.router.route.assert_called_once()

    def test_custom_task_id(self):
        self.hook.get_route_for_task("Test", candidates=[_cand()], task_id="my_123")
        reqs = self.router.route.call_args.kwargs.get("requirements") or self.router.route.call_args[1].get("requirements") or self.router.route.call_args[0][0]
        assert reqs.task_id == "my_123"

    def test_passes_policy(self):
        p = RoutingPolicy(policy_id="p1", name="P")
        self.hook.get_route_for_task("T", candidates=[_cand()], policy=p)
        assert self.router.route.call_args.kwargs.get("policy") is p

    def test_stage_route(self):
        self.hook.get_stage_route(ExecutionStage.ANALYSIS, _dec(), [_cand()])
        reqs = self.router.route.call_args.kwargs.get("requirements") or self.router.route.call_args[0][0]
        assert "analysis" in reqs.task_id
        assert reqs.quality.overall == QualityLevel.HIGH

    def test_verification_stage_strict(self):
        self.hook.get_stage_route(ExecutionStage.VERIFICATION, _dec(), [_cand()])
        reqs = self.router.route.call_args.kwargs.get("requirements") or self.router.route.call_args[0][0]
        assert reqs.quality.overall == QualityLevel.STRICT

    def test_stage_no_reqs_raises(self):
        with pytest.raises(ValueError, match="no requirements"):
            self.hook.get_stage_route(ExecutionStage.PLANNING, _dec(requirements=None), [_cand()])

    def test_replan_on_failure(self):
        assert self.hook.should_replan(_dec(), {"status": "FAILED"}) is True

    def test_no_replan_on_success(self):
        assert self.hook.should_replan(_dec(), {"status": "COMPLETED", "quality_score": 0.95}) is False

    def test_replan_low_quality(self):
        r = _reqs(quality=QualityRequirements(overall=QualityLevel.HIGH))
        assert self.hook.should_replan(_dec(requirements=r), {"quality_score": 0.5}) is True

    def test_replan_cost_overrun(self):
        r = _reqs(resources=ResourceConstraints(max_cost_usd=1.0))
        assert self.hook.should_replan(_dec(requirements=r), {"cost_usd": 5.0}) is True

    def test_no_replan_within_budget(self):
        r = _reqs(resources=ResourceConstraints(max_cost_usd=10.0))
        assert self.hook.should_replan(_dec(requirements=r), {"cost_usd": 5.0}) is False


# ── Verification Hook ─────────────────────────────────────────

class TestVerificationHook:
    def setup_method(self):
        self.h = VerificationRoutingHook()

    def test_standard(self):
        c = self.h.get_verification_config(_dec())
        assert c.quality_level == QualityLevel.STANDARD
        assert "schema_check" in c.checks_enabled
        assert c.strictness == 0.5
        assert c.require_human_review is False

    def test_high(self):
        r = _reqs(quality=QualityRequirements(overall=QualityLevel.HIGH))
        c = self.h.get_verification_config(_dec(requirements=r))
        assert c.quality_level == QualityLevel.HIGH
        assert "citation_check" in c.checks_enabled
        assert c.require_human_review is True

    def test_strict(self):
        r = _reqs(quality=QualityRequirements(overall=QualityLevel.STRICT))
        c = self.h.get_verification_config(_dec(requirements=r))
        assert c.quality_level == QualityLevel.STRICT
        assert "state_check" in c.checks_enabled

    def test_write_escalates(self):
        r = _reqs(security=SecurityRequirements(external_write_actions=True))
        c = self.h.get_verification_config(_dec(requirements=r))
        assert c.quality_level in (QualityLevel.HIGH, QualityLevel.STRICT)

    def test_sandbox_escalates(self):
        r = _reqs(security=SecurityRequirements(requires_sandbox=True))
        c = self.h.get_verification_config(_dec(requirements=r))
        assert c.quality_level in (QualityLevel.HIGH, QualityLevel.STRICT)

    def test_admin_strict(self):
        r = _reqs(security=SecurityRequirements(max_privilege_level="admin"))
        c = self.h.get_verification_config(_dec(requirements=r))
        assert c.quality_level == QualityLevel.STRICT

    def test_low_confidence_escalates(self):
        c = self.h.get_verification_config(_dec(decision_reason={"confidence": "LOW"}))
        assert c.quality_level in (QualityLevel.HIGH, QualityLevel.STRICT)

    def test_metadata(self):
        c = self.h.get_verification_config(_dec())
        assert c.metadata["decision_id"] == "dec_001"
        assert c.metadata["source"] == "c9_routing"

    def test_minimum(self):
        r = _reqs(quality=QualityRequirements(overall=QualityLevel.MINIMUM))
        c = self.h.get_verification_config(_dec(requirements=r))
        assert c.quality_level == QualityLevel.MINIMUM
        assert len(c.checks_enabled) == 2


# ── Kernel Hook ───────────────────────────────────────────────

class TestKernelHook:
    def setup_method(self):
        self.router = MagicMock()
        self.cache = MagicMock()
        self.router.route.return_value = _dec()
        self.hook = KernelRoutingHook(router=self.router, cache=self.cache)

    def test_resolve(self):
        self.cache.get.return_value = None
        self.cache.compute_cache_key.return_value = "ck_123"
        d = self.hook.resolve_execution_route(_reqs(), [_cand()])
        assert d.decision_id == "dec_001"
        self.router.route.assert_called_once()
        self.cache.put.assert_called_once()

    def test_cache_hit(self):
        self.cache.get.return_value = _route()
        self.cache.compute_cache_key.return_value = "ck_123"
        d = self.hook.resolve_execution_route(_reqs(), [_cand()])
        assert d.decision_reason.get("source") == "cache"
        self.router.route.assert_not_called()

    def test_no_cache(self):
        h = KernelRoutingHook(router=self.router, cache=None)
        d = h.resolve_execution_route(_reqs(), [_cand()])
        assert d.decision_id == "dec_001"

    def test_invalidate(self):
        self.cache.invalidate.return_value = True
        assert self.hook.invalidate_route("ck") is True

    def test_invalidate_no_cache(self):
        h = KernelRoutingHook(router=self.router, cache=None)
        assert h.invalidate_route("x") is False


# ── Golden Scenario ───────────────────────────────────────────

class TestGoldenScenario:
    def _runner(self, **ov):
        ext = MagicMock(); ext.extract.return_value = _reqs()
        cls_ = MagicMock(); cls_.classify.return_value = TaskClassification(primary_domain=TaskDomain.RESEARCH, confidence=0.85)
        gen = MagicMock(); gen.generate.return_value = [_cand("a", "x"), _cand("b", "y")]
        pol = MagicMock(); pol.apply.return_value = ([_cand("a", "x")], [_cand("b", "y")])
        rtr = MagicMock(); rtr.route.return_value = _dec()
        exp = MagicMock(); exp.explain.return_value = {"decision_id": "dec_001", "selected": {"model": "model-x"}}
        agg = MagicMock(); agg.aggregate.return_value = AggregatedEvidence(candidate_key="t", total_sample_count=5, confidence=EvidenceConfidence.MEDIUM)
        return GoldenScenarioRunner(
            extractor=ov.get("extractor", ext), classifier=ov.get("classifier", cls_),
            generator=ov.get("generator", gen), policy_engine=ov.get("policy_engine", pol),
            router=ov.get("router", rtr), explainer=ov.get("explainer", exp),
            evidence_aggregator=ov.get("evidence_aggregator", agg),
        )

    def test_complete(self):
        r = self._runner().run(task_description="Analyze medical paper")
        assert isinstance(r, GoldenScenarioResult)
        assert r.candidates_generated == 2
        assert r.candidates_after_policy == 2

    def test_with_policy(self):
        r = self._runner().run(task_description="T", policy=RoutingPolicy(policy_id="p1", name="P"))
        assert r.candidates_after_policy == 1

    def test_stages(self):
        r = self._runner().run(task_description="T")
        assert r.pipeline_stages == ["extract_requirements", "classify_task", "generate_candidates", "apply_policies", "aggregate_evidence", "route", "generate_explanation"]

    def test_explanation(self):
        r = self._runner().run(task_description="T")
        assert "decision_id" in r.explanation

    def test_custom_id(self):
        r = self._runner().run(task_description="T", task_id="custom_123")
        assert r.requirements.task_id == "custom_123"

    def test_domain(self):
        r = self._runner().run(task_description="Research topic")
        assert r.classification_domain == "RESEARCH"

    def test_timestamp(self):
        r = self._runner().run(task_description="T")
        assert r.timestamp.tzinfo is not None

    def test_arena_runs(self):
        r = self._runner().run(task_description="T", arena_runs=[_run(id="r1"), _run(id="r2")])
        assert r.evidence_count == 2
