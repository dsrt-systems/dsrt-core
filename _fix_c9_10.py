"""Fix all C9.10 integration modules and tests against real contracts."""
import pathlib

def w(path, content):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    print(f"  Wrote {p} ({len(content)} bytes)")

# ================================================================
# 1. arena_bridge.py
# ================================================================
w("core/routing/integrations/arena_bridge.py", '''\
"""C9.10 - Arena Evidence Bridge.

Bridges C8 Arena run data to C9 RoutingEvidence contracts.
Uses dict-based interface to avoid hard coupling to C8 internals.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.routing.contracts import RoutingEvidence
from core.routing.enums import EvidenceSourceType


_USABLE_STATUSES = frozenset({"COMPLETED"})

_METRIC_ALIASES: dict[str, str] = {
    "task_success": "quality_score",
    "accuracy": "quality_score",
    "f1_score": "quality_score",
    "latency_ms": "latency_ms",
    "p50_latency_ms": "latency_ms",
    "cost_usd": "cost_usd",
    "total_cost": "cost_usd",
    "reliability": "reliability_score",
    "success_rate": "reliability_score",
    "total_tokens": "token_usage",
    "token_count": "token_usage",
}


class ArenaEvidenceBridge:
    """Transforms C8 Arena data into C9 routing evidence."""

    def __init__(self, max_evidence_age_hours: int = 168) -> None:
        self._max_age_hours = max_evidence_age_hours

    def transform_run_to_evidence(
        self,
        run_data: dict[str, Any],
        metrics: dict[str, Any] | None = None,
    ) -> RoutingEvidence | None:
        if not self._is_run_usable(run_data):
            return None

        metrics = metrics or run_data.get("metrics") or {}

        quality = self._extract_metric(metrics, "quality_score", 0.0)
        latency = self._extract_metric(metrics, "latency_ms", 0.0)
        cost = self._extract_metric(metrics, "cost_usd", 0.0)
        reliability = self._extract_metric(metrics, "reliability_score", 0.0)
        tokens = self._extract_metric(metrics, "token_usage", 0.0)

        ts = run_data.get("completed_at") or run_data.get("created_at")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                ts = datetime.now(timezone.utc)
        elif ts is None:
            ts = datetime.now(timezone.utc)

        source_type = self._infer_source_type(run_data)

        return RoutingEvidence(
            source_type=source_type,
            benchmark_id=run_data.get("benchmark_id"),
            benchmark_version=run_data.get("benchmark_version"),
            agent_version=run_data.get("agent_version") or run_data.get("agent_slug"),
            model_version=run_data.get("model_version") or run_data.get("model_slug"),
            world_version=run_data.get("world_version") or run_data.get("world_slug"),
            sample_count=1,
            metrics={
                "quality_score": quality,
                "latency_ms": latency,
                "cost_usd": cost,
                "reliability_score": reliability,
                "token_usage": tokens,
                "agent_slug": run_data.get("agent_slug", ""),
                "model_slug": run_data.get("model_slug", ""),
                "provider_id": run_data.get("provider_id", ""),
                "configuration_hash": run_data.get("configuration_hash", ""),
                "repetition": run_data.get("repetition", 1),
            },
            observed_at=ts,
        )

    def transform_runs_batch(
        self, runs: list[dict[str, Any]],
    ) -> list[RoutingEvidence]:
        results: list[RoutingEvidence] = []
        for run in runs:
            ev = self.transform_run_to_evidence(run)
            if ev is not None:
                results.append(ev)
        return results

    def _is_run_usable(self, run_data: dict[str, Any]) -> bool:
        status = run_data.get("status", "")
        if status not in _USABLE_STATUSES:
            return False
        if not run_data.get("agent_slug") and not run_data.get("model_slug"):
            return False
        return True

    def _extract_metric(
        self, metrics: dict[str, Any], c9_key: str, default: float = 0.0,
    ) -> float:
        if c9_key in metrics:
            return self._to_float(metrics[c9_key], default)
        for arena_key, mapped in _METRIC_ALIASES.items():
            if mapped == c9_key and arena_key in metrics:
                return self._to_float(metrics[arena_key], default)
        return default

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _infer_source_type(run_data: dict[str, Any]) -> EvidenceSourceType:
        if run_data.get("benchmark_id"):
            return EvidenceSourceType.ARENA_BENCHMARK
        if run_data.get("experiment_id"):
            return EvidenceSourceType.ARENA_EXPERIMENT
        return EvidenceSourceType.ARENA_BENCHMARK
''')

# ================================================================
# 2. orchestration_hook.py
# ================================================================
w("core/routing/integrations/orchestration_hook.py", '''\
"""C9.10 - Orchestration Routing Hook.

Provides C6 orchestration with C9 routing recommendations.
"""
from __future__ import annotations

import uuid
from typing import Any

from core.routing.contracts import (
    AggregatedEvidence,
    QualityRequirements,
    RouteCandidate,
    RouteDecision,
    RoutingPolicy,
    RoutingProfile,
    TaskRequirements,
)
from core.routing.enums import ExecutionStage, QualityLevel
from core.routing.requirements.extractor import RequirementExtractor
from core.routing.selector.router import IntelligenceRouter


_STAGE_QUALITY: dict[ExecutionStage, QualityLevel] = {
    ExecutionStage.PLANNING: QualityLevel.STANDARD,
    ExecutionStage.RETRIEVAL: QualityLevel.STANDARD,
    ExecutionStage.ANALYSIS: QualityLevel.HIGH,
    ExecutionStage.SYNTHESIS: QualityLevel.HIGH,
    ExecutionStage.VERIFICATION: QualityLevel.STRICT,
    ExecutionStage.FINALIZATION: QualityLevel.STANDARD,
}


class OrchestrationRoutingHook:
    """Hook for C6 orchestration to consult C9 routing."""

    def __init__(
        self,
        router: IntelligenceRouter,
        extractor: RequirementExtractor | None = None,
    ) -> None:
        self._router = router
        self._extractor = extractor or RequirementExtractor()

    def get_route_for_task(
        self,
        task_description: str,
        candidates: list[RouteCandidate],
        task_id: str | None = None,
        policy: RoutingPolicy | None = None,
        profile: RoutingProfile | None = None,
        evidence_map: dict[str, AggregatedEvidence] | None = None,
        hints: dict[str, Any] | None = None,
    ) -> RouteDecision:
        task_id = task_id or f"task_{uuid.uuid4().hex[:12]}"
        requirements = self._extractor.extract(
            task_id=task_id,
            description=task_description,
            hints=hints,
        )
        return self._router.route(
            requirements=requirements,
            candidates=candidates,
            policy=policy,
            profile=profile,
            evidence_map=evidence_map,
        )

    def get_stage_route(
        self,
        stage: ExecutionStage,
        parent_decision: RouteDecision,
        candidates: list[RouteCandidate],
        policy: RoutingPolicy | None = None,
    ) -> RouteDecision:
        parent_reqs = parent_decision.requirements
        if parent_reqs is None:
            raise ValueError("Parent decision has no requirements")

        stage_quality = _STAGE_QUALITY.get(stage, parent_reqs.quality.overall)
        stage_reqs = TaskRequirements(
            task_id=f"{parent_reqs.task_id}_{stage.value.lower()}",
            description=f"[{stage.value}] {parent_reqs.description}",
            classification=parent_reqs.classification,
            capabilities=parent_reqs.capabilities,
            quality=QualityRequirements(overall=stage_quality),
            resources=parent_reqs.resources,
            security=parent_reqs.security,
            preferred_tools=parent_reqs.preferred_tools,
            required_tools=parent_reqs.required_tools,
            output_type=parent_reqs.output_type,
            metadata={
                **parent_reqs.metadata,
                "stage": stage.value,
                "parent_task_id": parent_reqs.task_id,
            },
        )
        return self._router.route(
            requirements=stage_reqs,
            candidates=candidates,
            policy=policy,
        )

    def should_replan(
        self,
        current_decision: RouteDecision,
        execution_feedback: dict[str, Any],
    ) -> bool:
        if execution_feedback.get("status") == "FAILED":
            return True
        reqs = current_decision.requirements
        if reqs is None:
            return False
        quality_score = execution_feedback.get("quality_score")
        if quality_score is not None:
            thresholds = {
                QualityLevel.STRICT: 0.95,
                QualityLevel.HIGH: 0.85,
                QualityLevel.STANDARD: 0.7,
                QualityLevel.MINIMUM: 0.5,
            }
            if quality_score < thresholds.get(reqs.quality.overall, 0.7):
                return True
        cost = execution_feedback.get("cost_usd")
        if cost is not None and reqs.resources.max_cost_usd is not None:
            if cost > reqs.resources.max_cost_usd * 2:
                return True
        duration = execution_feedback.get("duration_seconds")
        if duration is not None and reqs.resources.max_duration_seconds is not None:
            if duration > reqs.resources.max_duration_seconds * 1.5:
                return True
        return False
''')

# ================================================================
# 3. verification_hook.py
# ================================================================
w("core/routing/integrations/verification_hook.py", '''\
"""C9.10 - Verification Routing Hook.

Maps C9 route decisions to C7 verification configurations
using QualityLevel from task requirements.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.routing.contracts import RouteDecision
from core.routing.enums import QualityLevel


@dataclass(frozen=True)
class VerificationConfig:
    quality_level: QualityLevel
    checks_enabled: tuple[str, ...]
    strictness: float
    max_verification_latency_ms: int
    require_human_review: bool
    metadata: dict[str, Any] = field(default_factory=dict)


class VerificationRoutingHook:
    CHECK_SETS: dict[QualityLevel, tuple[str, ...]] = {
        QualityLevel.MINIMUM: ("schema_check", "completeness_check"),
        QualityLevel.STANDARD: (
            "schema_check", "completeness_check",
            "constraint_check", "claim_check",
        ),
        QualityLevel.HIGH: (
            "schema_check", "completeness_check",
            "constraint_check", "claim_check",
            "citation_check", "artifact_check",
        ),
        QualityLevel.STRICT: (
            "schema_check", "completeness_check",
            "constraint_check", "claim_check",
            "citation_check", "artifact_check",
            "tool_check", "state_check",
        ),
    }
    STRICTNESS: dict[QualityLevel, float] = {
        QualityLevel.MINIMUM: 0.25,
        QualityLevel.STANDARD: 0.5,
        QualityLevel.HIGH: 0.75,
        QualityLevel.STRICT: 1.0,
    }
    LATENCY: dict[QualityLevel, int] = {
        QualityLevel.MINIMUM: 500,
        QualityLevel.STANDARD: 2000,
        QualityLevel.HIGH: 5000,
        QualityLevel.STRICT: 15000,
    }

    def get_verification_config(self, decision: RouteDecision) -> VerificationConfig:
        level = self._determine_level(decision)
        return VerificationConfig(
            quality_level=level,
            checks_enabled=self.CHECK_SETS.get(level, self.CHECK_SETS[QualityLevel.STANDARD]),
            strictness=self.STRICTNESS.get(level, 0.5),
            max_verification_latency_ms=self.LATENCY.get(level, 2000),
            require_human_review=level in (QualityLevel.HIGH, QualityLevel.STRICT),
            metadata={
                "decision_id": decision.decision_id,
                "task_id": decision.task_id,
                "source": "c9_routing",
            },
        )

    def _determine_level(self, decision: RouteDecision) -> QualityLevel:
        base = QualityLevel.STANDARD
        reqs = decision.requirements
        if reqs is not None:
            base = reqs.quality.overall
            if reqs.security.external_write_actions:
                base = self._max(base, QualityLevel.HIGH)
            if reqs.security.requires_sandbox:
                base = self._max(base, QualityLevel.HIGH)
            if reqs.security.max_privilege_level in ("elevated", "admin"):
                base = self._max(base, QualityLevel.STRICT)
        reason = decision.decision_reason or {}
        if str(reason.get("confidence", "")).upper() == "LOW":
            base = self._max(base, QualityLevel.HIGH)
        return base

    @staticmethod
    def _max(a: QualityLevel, b: QualityLevel) -> QualityLevel:
        order = [QualityLevel.MINIMUM, QualityLevel.STANDARD, QualityLevel.HIGH, QualityLevel.STRICT]
        return order[max(order.index(a) if a in order else 1, order.index(b) if b in order else 1)]
''')

# ================================================================
# 4. kernel_hook.py
# ================================================================
w("core/routing/integrations/kernel_hook.py", '''\
"""C9.10 - Kernel Routing Hook."""
from __future__ import annotations

from core.routing.contracts import (
    AggregatedEvidence,
    RouteCandidate,
    RouteDecision,
    RoutingPolicy,
    RoutingProfile,
    TaskRequirements,
)
from core.routing.enums import RoutingStatus
from core.routing.cache.manager import RouteCacheManager
from core.routing.selector.router import IntelligenceRouter


class KernelRoutingHook:
    def __init__(
        self,
        router: IntelligenceRouter,
        cache: RouteCacheManager | None = None,
    ) -> None:
        self._router = router
        self._cache = cache

    def resolve_execution_route(
        self,
        requirements: TaskRequirements,
        candidates: list[RouteCandidate],
        policy: RoutingPolicy | None = None,
        profile: RoutingProfile | None = None,
        evidence_map: dict[str, AggregatedEvidence] | None = None,
    ) -> RouteDecision:
        cache_key = None
        if self._cache is not None:
            cache_key = self._cache.compute_cache_key(
                requirements_hash=requirements.requirements_hash(),
                policy_id=policy.policy_id if policy else None,
                policy_version=policy.version if policy else None,
                profile_id=profile.profile_id if profile else None,
            )
            cached_route = self._cache.get(cache_key)
            if cached_route is not None:
                return RouteDecision(
                    decision_id=f"cached_{cache_key[:16]}",
                    task_id=requirements.task_id,
                    status=RoutingStatus.COMPLETED,
                    requirements=requirements,
                    selected_route=cached_route,
                    decision_reason={"source": "cache", "cache_key": cache_key},
                )

        decision = self._router.route(
            requirements=requirements,
            candidates=candidates,
            policy=policy,
            profile=profile,
            evidence_map=evidence_map,
        )

        if self._cache is not None and cache_key and decision.selected_route:
            self._cache.put(cache_key, decision.selected_route, decision.decision_id)

        return decision

    def invalidate_route(self, cache_key: str) -> bool:
        if self._cache is None:
            return False
        return self._cache.invalidate(cache_key)
''')

# ================================================================
# 5. golden_scenario.py
# ================================================================
w("core/routing/integrations/golden_scenario.py", '''\
"""C9.10 - Golden Scenario Runner (spec sections 57-58)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.routing.contracts import (
    AgentCapabilityProfile,
    ModelCapabilityProfile,
    RouteDecision,
    RoutingPolicy,
    RoutingProfile,
    TaskRequirements,
)
from core.routing.requirements.extractor import RequirementExtractor
from core.routing.analyzer.classifier import TaskClassifier
from core.routing.candidates.generator import CandidateGenerator
from core.routing.policies.engine import PolicyEngine
from core.routing.selector.router import IntelligenceRouter
from core.routing.selector.explainer import DecisionExplainer
from core.routing.evidence.aggregator import EvidenceAggregator
from core.routing.integrations.arena_bridge import ArenaEvidenceBridge


@dataclass
class GoldenScenarioResult:
    task_description: str
    requirements: TaskRequirements
    classification_domain: str
    evidence_count: int
    candidates_generated: int
    candidates_after_policy: int
    decision: RouteDecision
    explanation: dict[str, Any]
    pipeline_stages: list[str]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class GoldenScenarioRunner:
    def __init__(
        self,
        extractor: RequirementExtractor | None = None,
        classifier: TaskClassifier | None = None,
        generator: CandidateGenerator | None = None,
        policy_engine: PolicyEngine | None = None,
        router: IntelligenceRouter | None = None,
        explainer: DecisionExplainer | None = None,
        evidence_aggregator: EvidenceAggregator | None = None,
        arena_bridge: ArenaEvidenceBridge | None = None,
    ) -> None:
        self._extractor = extractor or RequirementExtractor()
        self._classifier = classifier or TaskClassifier()
        self._generator = generator or CandidateGenerator()
        self._policy_engine = policy_engine or PolicyEngine()
        self._router = router or IntelligenceRouter()
        self._explainer = explainer or DecisionExplainer()
        self._evidence_aggregator = evidence_aggregator or EvidenceAggregator()
        self._arena_bridge = arena_bridge or ArenaEvidenceBridge()

    def run(
        self,
        task_description: str,
        task_id: str | None = None,
        agents: list[AgentCapabilityProfile] | None = None,
        models: list[ModelCapabilityProfile] | None = None,
        worlds: list[dict[str, Any]] | None = None,
        policy: RoutingPolicy | None = None,
        profile: RoutingProfile | None = None,
        arena_runs: list[dict[str, Any]] | None = None,
    ) -> GoldenScenarioResult:
        stages: list[str] = []
        task_id = task_id or f"golden_{uuid.uuid4().hex[:12]}"

        stages.append("extract_requirements")
        requirements = self._extractor.extract(task_id=task_id, description=task_description)

        stages.append("classify_task")
        classification = self._classifier.classify(task_description)

        stages.append("generate_candidates")
        candidates = self._generator.generate(
            requirements=requirements,
            eligible_agents=agents or [],
            eligible_models=models or [],
            available_worlds=worlds,
        )
        candidates_generated = len(candidates)

        stages.append("apply_policies")
        if policy is not None:
            eligible, rejected = self._policy_engine.apply(
                candidates=candidates, policy=policy,
                requirements=requirements, profile=profile,
            )
        else:
            eligible = [c for c in candidates if c.is_eligible]
            rejected = [c for c in candidates if not c.is_eligible]
        candidates_after_policy = len(eligible)

        stages.append("aggregate_evidence")
        evidence_map = {}
        arena_count = 0
        if arena_runs:
            arena_ev = self._arena_bridge.transform_runs_batch(arena_runs)
            arena_count = len(arena_ev)
            for ev in arena_ev:
                key = f"{ev.agent_version}:{ev.model_version}"
                if key not in evidence_map:
                    evidence_map[key] = self._evidence_aggregator.aggregate(key, [ev])

        stages.append("route")
        decision = self._router.route(
            requirements=requirements,
            candidates=eligible if eligible else candidates,
            policy=policy,
            profile=profile,
            evidence_map=evidence_map if evidence_map else None,
        )

        stages.append("generate_explanation")
        explanation = self._explainer.explain(decision)

        return GoldenScenarioResult(
            task_description=task_description,
            requirements=requirements,
            classification_domain=classification.primary_domain.value,
            evidence_count=arena_count,
            candidates_generated=candidates_generated,
            candidates_after_policy=candidates_after_policy,
            decision=decision,
            explanation=explanation,
            pipeline_stages=stages,
        )
''')

# ================================================================
# 6. __init__.py
# ================================================================
w("core/routing/integrations/__init__.py", '''\
"""C9.10 - Cross-Phase Integration Bridges."""
from core.routing.integrations.arena_bridge import ArenaEvidenceBridge
from core.routing.integrations.orchestration_hook import OrchestrationRoutingHook
from core.routing.integrations.verification_hook import VerificationRoutingHook, VerificationConfig
from core.routing.integrations.kernel_hook import KernelRoutingHook
from core.routing.integrations.golden_scenario import GoldenScenarioRunner, GoldenScenarioResult

__all__ = [
    "ArenaEvidenceBridge",
    "OrchestrationRoutingHook",
    "VerificationRoutingHook",
    "VerificationConfig",
    "KernelRoutingHook",
    "GoldenScenarioRunner",
    "GoldenScenarioResult",
]
''')

# ================================================================
# 7. test file
# ================================================================
w("tests/test_c9_integration.py", '''\
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
        "metrics": metrics or {"task_success": 0.92, "latency_ms": 1200, "cost_usd": 0.05, "reliability": 0.95, "total_tokens": 4500},
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
        assert r.candidates_after_policy == 1

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
''')

print("\n=== All C9.10 files written successfully ===")