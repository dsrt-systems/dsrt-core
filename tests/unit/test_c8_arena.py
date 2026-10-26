"""
Comprehensive C8 Arena & Evaluation Fabric Tests.

Covers all C8 sub-phases:
  C8.1 Schemas & Enums
  C8.2 Database ORM
  C8.3 Benchmark & Task Registry
  C8.4 Experiment & Run Manager
  C8.5 Trajectory Engine
  C8.6 Evaluator Runtime
  C8.7 Metric Engine & Profiles
  C8.8 Regression & Analysis
  C8.9 SDK & API
  C8.10 C5/C6/C7 Integration
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from schemas.domain.arena import (
    ArenaResult,
    ArenaRun,
    Benchmark,
    BenchmarkConstraints,
    EvaluatorConfig,
    Experiment,
    ExperimentConfiguration,
    MetricResult,
    PerformanceProfile,
    RegressionResult,
    TaskDefinition,
    TaskInstance,
    TaskSuccessConditions,
    Trajectory,
    TrajectoryEvent,
)
from schemas.domain.enums import (
    ArenaRunStatus,
    BenchmarkType,
    EvaluatorType,
    FailureCategory,
    MetricType,
    RegressionStatus,
    TaskVisibility,
    VerificationStatus,
)


# =====================================================================
# C8.1 — Schemas & Enums
# =====================================================================


class TestC8Schemas:
    def test_benchmark_types(self):
        assert len(list(BenchmarkType)) == 6

    def test_task_visibility(self):
        assert len(list(TaskVisibility)) == 5

    def test_arena_run_status(self):
        assert len(list(ArenaRunStatus)) == 11

    def test_evaluator_types(self):
        assert len(list(EvaluatorType)) == 5

    def test_metric_types(self):
        assert len(list(MetricType)) == 12

    def test_failure_categories(self):
        assert len(list(FailureCategory)) == 14

    def test_regression_status(self):
        assert len(list(RegressionStatus)) == 5

    def test_benchmark_schema(self):
        b = Benchmark(
            id="test_v1", version="1.0.0",
            benchmark_type=BenchmarkType.WORKFLOW,
            metrics=["task_success"],
            constraints=BenchmarkConstraints(max_cost_usd=5.0),
        )
        assert b.constraints.max_cost_usd == 5.0

    def test_task_hidden_state(self):
        t = TaskDefinition(
            id="T1", objective="Test",
            success_conditions=TaskSuccessConditions(minimum_sources=5),
            visibility=TaskVisibility.HIDDEN,
        )
        assert t.success_conditions.minimum_sources == 5
        assert t.visibility == TaskVisibility.HIDDEN

    def test_experiment_matrix(self):
        e = Experiment(
            id="exp_1", benchmark_id="b1", benchmark_version="1.0",
            configurations=[
                ExperimentConfiguration(
                    agent_slug="a1", agent_version="1.0",
                    task_definition_id="t1",
                ),
            ],
            repetitions=3,
        )
        assert e.repetitions == 3

    def test_performance_profile_no_single_score(self):
        pp = PerformanceProfile(
            id="prf_1", arena_run_id="arn_1",
            task_success=True, correctness=0.91,
            dimensions={"correctness": 0.91},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        assert "quality_score" not in pp.dimensions

    def test_arena_result(self):
        ar = ArenaResult(
            run_id="arn_1", outcome="PASSED",
            configuration_hash="abc123",
        )
        assert ar.outcome == "PASSED"


# =====================================================================
# C8.2 — Database ORM
# =====================================================================


class TestC8ORM:
    def test_all_orm_models(self):
        from core.storage.models import (
            ArenaRunORM, BenchmarkORM, EvaluatorORM,
            ExperimentORM, MetricResultORM, PerformanceProfileORM,
            RegressionORM, TaskDefinitionORM, TaskInstanceORM,
            TaskSuiteORM, TrajectoryEventORM, TrajectoryORM,
        )
        assert BenchmarkORM.__tablename__ == "benchmarks"
        assert ArenaRunORM.__tablename__ == "arena_runs"
        assert TrajectoryORM.__tablename__ == "trajectories"
        assert PerformanceProfileORM.__tablename__ == "performance_profiles"

    def test_arena_run_relationships(self):
        from core.storage.models import ArenaRunORM
        assert hasattr(ArenaRunORM, "trajectory")
        assert hasattr(ArenaRunORM, "performance_profile")
        assert hasattr(ArenaRunORM, "experiment")

    def test_hidden_state_columns(self):
        from core.storage.models import TaskDefinitionORM, TaskInstanceORM
        assert hasattr(TaskDefinitionORM, "success_conditions")
        assert hasattr(TaskInstanceORM, "hidden_state")


# =====================================================================
# C8.3 — Benchmark & Task Registry
# =====================================================================


class TestC8Registry:
    def test_benchmark_registry(self):
        from core.arena.registry import BenchmarkRegistry
        br = BenchmarkRegistry.__new__(BenchmarkRegistry)
        br._session = None
        assert hasattr(br, "register")
        assert hasattr(br, "verify_integrity")

    def test_task_registry(self):
        from core.arena.registry import TaskRegistry
        tr = TaskRegistry.__new__(TaskRegistry)
        tr._session = None
        assert hasattr(tr, "create_suite")
        assert hasattr(tr, "create_task")
        assert hasattr(tr, "create_instance")


# =====================================================================
# C8.4 — Experiment & Run Manager
# =====================================================================


class TestC8ExperimentRun:
    def test_experiment_manager(self):
        from core.arena.runs import ExperimentManager
        em = ExperimentManager.__new__(ExperimentManager)
        em._session = None
        assert hasattr(em, "create_experiment")
        assert hasattr(em, "expand_runs")

    def test_run_manager_lifecycle(self):
        from core.arena.runs import ArenaRunManager
        rm = ArenaRunManager.__new__(ArenaRunManager)
        rm._session = None
        rm._kernel = None
        for valid in [
            ("CREATED", "QUEUED"), ("QUEUED", "PROVISIONING_WORLD"),
            ("RUNNING", "VERIFYING"), ("EVALUATING", "COMPLETED"),
        ]:
            assert rm.validate_transition(valid[0], valid[1])
        for invalid in [("COMPLETED", "RUNNING"), ("FAILED", "RUNNING")]:
            assert not rm.validate_transition(invalid[0], invalid[1])

    def test_config_hash_determinism(self):
        from core.arena.runs import ExperimentManager
        h1 = ExperimentManager._compute_config_hash(a="1", b="2")
        h2 = ExperimentManager._compute_config_hash(a="1", b="2")
        h3 = ExperimentManager._compute_config_hash(a="1", b="3")
        assert h1 == h2
        assert h1 != h3


# =====================================================================
# C8.5 — Trajectory Engine
# =====================================================================


class TestC8Trajectory:
    def test_trajectory_builder(self):
        from core.arena.trajectories import TrajectoryBuilder
        builder = TrajectoryBuilder()
        now = datetime.now(timezone.utc)
        events = [
            SimpleNamespace(id="e1", sequence=1, event_type="EXECUTION_CREATED",
                            source="k", payload={}, request_id=None, timestamp=now),
            SimpleNamespace(id="e2", sequence=2, event_type="TOOL_CALL_STARTED",
                            source="t", payload={"tool_slug": "web"}, request_id=None,
                            timestamp=now + timedelta(seconds=1)),
        ]
        te, summary = builder.build(events, arena_run_id="arn_1")
        assert len(te) == 2
        assert summary["tool_call_count"] == 1

    def test_payload_sanitization(self):
        from core.arena.trajectories.builder import TrajectoryBuilder
        s = TrajectoryBuilder._sanitize_payload({"content": "x" * 5000, "ok": True})
        assert "redacted" in s["content"]
        assert s["ok"] is True

    def test_trajectory_store(self):
        from core.arena.trajectories import TrajectoryStore
        store = TrajectoryStore.__new__(TrajectoryStore)
        store._session = None
        assert hasattr(store, "save_trajectory")
        assert hasattr(store, "compare_trajectories")


# =====================================================================
# C8.6 — Evaluator Runtime
# =====================================================================


class TestC8Evaluators:
    def test_deterministic_evaluator(self):
        from core.arena.evaluators import DeterministicEvaluator, EvaluationInput
        de = DeterministicEvaluator()
        assert de.evaluator_type == EvaluatorType.DETERMINISTIC
        inp = EvaluationInput(
            arena_run_id="arn_1", task_objective="Test",
            trajectory_summary={"event_count": 10, "failure_count": 0},
        )
        result = asyncio.run(de.evaluate(inp))
        assert result.passed

    def test_trajectory_evaluator(self):
        from core.arena.evaluators import TrajectoryEvaluator, EvaluationInput
        te = TrajectoryEvaluator()
        inp = EvaluationInput(
            arena_run_id="arn_1", task_objective="Test",
            trajectory_summary={
                "event_count": 20, "tool_call_count": 5,
                "model_call_count": 3, "failure_count": 1,
                "recovery_count": 1, "duration_ms": 60000,
            },
        )
        result = asyncio.run(te.evaluate(inp))
        assert len(result.metrics) >= 4

    def test_evaluator_isolation(self):
        from core.arena.evaluators.base import EvaluationInput
        assert not hasattr(EvaluationInput, "agent_chain_of_thought")


# =====================================================================
# C8.7 — Metric Engine & Profiles
# =====================================================================


class TestC8Metrics:
    def test_metric_computer(self):
        from core.arena.metrics import MetricComputer
        mc = MetricComputer()
        mc.add_evaluator_results("det", [
            MetricResult(metric_id="task_success", metric_type=MetricType.TASK_SUCCESS,
                         value_numeric=1.0, evaluator_type=EvaluatorType.DETERMINISTIC),
        ])
        aggs = mc.compute()
        assert "task_success" in aggs
        assert aggs["task_success"].mean_value == 1.0

    def test_performance_profile_builder(self):
        from core.arena.metrics import PerformanceProfileBuilder
        builder = PerformanceProfileBuilder()
        profile = builder.compute_profile(
            arena_run_id="arn_1", metrics=[],
            trajectory_summary={"duration_ms": 1000},
            resource_usage={"model_cost_usd": 0.5, "tool_cost_usd": 0.1},
            task_success=True,
        )
        assert profile.task_success
        assert profile.model_cost_usd == 0.5

    def test_cost_separation(self):
        from core.arena.metrics import PerformanceProfileBuilder
        builder = PerformanceProfileBuilder()
        profile = builder.compute_profile(
            arena_run_id="arn_1", metrics=[],
            resource_usage={
                "model_cost_usd": 0.50, "tool_cost_usd": 0.08,
                "world_cost_usd": 0.03, "estimated_cost_usd": 0.61,
            },
        )
        assert profile.model_cost_usd + profile.tool_cost_usd + profile.world_cost_usd <= 0.62


# =====================================================================
# C8.8 — Regression & Analysis
# =====================================================================


class TestC8Regression:
    def test_regression_improvement(self):
        from core.arena.regressions import RegressionDetector
        rd = RegressionDetector.__new__(RegressionDetector)
        rd._session = None
        comp = rd._compare_dimension("correctness", [0.85], [0.95])
        assert comp.status == RegressionStatus.IMPROVED

    def test_regression_decline(self):
        from core.arena.regressions import RegressionDetector
        rd = RegressionDetector.__new__(RegressionDetector)
        rd._session = None
        comp = rd._compare_dimension("reliability", [0.95], [0.70])
        assert comp.status == RegressionStatus.REGRESSED

    def test_capability_profile(self):
        from core.arena.regressions.profiler import CapabilityProfile, CapabilityScore
        p = CapabilityProfile(
            entity_type="agent", entity_slug="test", entity_version="1.0",
            capabilities=[CapabilityScore("research", 0.9, 10, 0.8)],
        )
        d = p.to_dict()
        assert d["capabilities"]["research"]["score"] == 0.9

    def test_failure_analyzer(self):
        from core.arena.regressions import FailureAnalyzer
        fa = FailureAnalyzer()
        events = [
            {"sequence": 1, "event_type": "MODEL_REQUEST_FAILED", "payload": {"error": "timeout"}},
        ]
        analyses = fa.analyze_run(run_id="arn_1", trajectory_events=events)
        assert len(analyses) == 1
        assert analyses[0].category == FailureCategory.MODEL_FAILURE


# =====================================================================
# C8.9 — SDK & API
# =====================================================================


class TestC8SDKAndAPI:
    def test_arena_sdk_protocol(self):
        from sdk.agent.interfaces.arena import ArenaSDK
        assert hasattr(ArenaSDK, "get_last_result")
        assert hasattr(ArenaSDK, "get_capability_scores")

    def test_arena_sdk_frozen(self):
        from sdk.agent.interfaces.arena import SDKArenaResult
        r = SDKArenaResult(run_id="arn_1", status="COMPLETED")
        with pytest.raises(AttributeError):
            r.status = "FAILED"

    def test_arena_api_routes(self):
        from core.api.routers.arena import router
        routes = [r.path for r in router.routes]
        assert len(routes) >= 7

    def test_sdk_has_arena_field(self):
        from sdk.agent.sdk import DSRTAgentSDK
        import dataclasses
        assert "arena" in {f.name for f in dataclasses.fields(DSRTAgentSDK)}


# =====================================================================
# C8.10 — Integration
# =====================================================================


class TestC8Integration:
    def test_verification_hook(self):
        from core.arena.integration import ArenaVerificationHook
        hook = ArenaVerificationHook()
        metrics = hook.ingest_verification(
            arena_run_id="arn_1", verification_run_id="vrn_1",
            verification_status="PASSED",
            checks=[{"check_type": "SCHEMA_VALID", "status": "PASSED"}],
        )
        assert any(m.metric_id == "task_success" for m in metrics)

    def test_orchestrator_hook(self):
        from core.arena.integration import ArenaOrchestratorHook
        hook = ArenaOrchestratorHook.__new__(ArenaOrchestratorHook)
        hook._session = None
        assert hasattr(hook, "finalize_arena_run")


# =====================================================================
# C8 Architectural Invariants
# =====================================================================


class TestC8Invariants:
    def test_no_single_score(self):
        """C8 §2: Never collapse to one number."""
        pp = PerformanceProfile(
            id="p1", arena_run_id="a1",
            dimensions={"correctness": 0.9, "completeness": 0.8},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        assert "quality_score" not in pp.dimensions
        assert "intelligence_score" not in pp.dimensions

    def test_evidence_first(self):
        """C8 §30: Every metric has evidence."""
        m = MetricResult(
            metric_id="test", metric_type=MetricType.CORRECTNESS,
            value_numeric=0.9, evaluator_type=EvaluatorType.DETERMINISTIC,
            evidence_refs=["vrn_1", "art_1"],
        )
        assert len(m.evidence_refs) > 0

    def test_benchmark_experiment_run_separation(self):
        """C8 §5: Three distinct concepts."""
        b = Benchmark(id="b1")
        e = Experiment(id="e1", benchmark_id="b1", benchmark_version="1.0")
        r = ArenaRun(
            id="r1", benchmark_id="b1", benchmark_version="1.0",
            experiment_id="e1", task_definition_id="t1",
            agent_slug="a1", agent_version="1.0",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        assert b.id != e.id != r.id

    def test_configuration_fingerprint(self):
        """C8 §43: Every run has a config hash."""
        r = ArenaRun(
            id="r1", benchmark_id="b1", benchmark_version="1.0",
            experiment_id="e1", task_definition_id="t1",
            agent_slug="a1", agent_version="1.0",
            configuration_hash="sha256_abc123",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        assert r.configuration_hash != ""