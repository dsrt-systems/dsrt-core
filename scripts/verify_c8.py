"""
C8 Phase Certification Script.
Run: python scripts/verify_c8.py
"""

from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def verify_c8() -> bool:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        checks.append((name, condition, detail))

    # C8.1
    try:
        from schemas.domain.enums import (
            BenchmarkType, TaskVisibility, ArenaRunStatus,
            EvaluatorType, MetricType, FailureCategory, RegressionStatus,
        )
        from schemas.domain.arena import (
            Benchmark, TaskDefinition, Experiment, ArenaRun,
            Trajectory, MetricResult, PerformanceProfile,
            RegressionResult, ArenaResult,
        )
        assert len(list(BenchmarkType)) == 6
        assert len(list(FailureCategory)) == 14
        check("C8.1 Schemas and Enums", True)
    except Exception as e:
        check("C8.1 Schemas and Enums", False, str(e))

    # C8.2
    try:
        from core.storage.models import (
            BenchmarkORM, TaskSuiteORM, TaskDefinitionORM,
            ExperimentORM, ArenaRunORM, TrajectoryORM,
            TrajectoryEventORM, EvaluatorORM, MetricResultORM,
            PerformanceProfileORM, RegressionORM,
        )
        check("C8.2 Database Models", True)
    except Exception as e:
        check("C8.2 Database Models", False, str(e))

    # C8.3
    try:
        from core.arena.registry import BenchmarkRegistry, TaskRegistry
        br = BenchmarkRegistry.__new__(BenchmarkRegistry)
        br._session = None
        assert hasattr(br, "register")
        check("C8.3 Benchmark and Task Registry", True)
    except Exception as e:
        check("C8.3 Benchmark and Task Registry", False, str(e))

    # C8.4
    try:
        from core.arena.runs import ExperimentManager, ArenaRunManager
        rm = ArenaRunManager.__new__(ArenaRunManager)
        rm._session = None
        rm._kernel = None
        assert rm.validate_transition("CREATED", "QUEUED")
        check("C8.4 Experiment and Run Manager", True)
    except Exception as e:
        check("C8.4 Experiment and Run Manager", False, str(e))

    # C8.5
    try:
        from core.arena.trajectories import TrajectoryBuilder, TrajectoryStore
        b = TrajectoryBuilder()
        assert hasattr(b, "build")
        check("C8.5 Trajectory Engine", True)
    except Exception as e:
        check("C8.5 Trajectory Engine", False, str(e))

    # C8.6
    try:
        from core.arena.evaluators import (
            DeterministicEvaluator, TrajectoryEvaluator, EvaluationInput,
        )
        de = DeterministicEvaluator()
        assert de.evaluator_type.value == "deterministic"
        check("C8.6 Evaluator Runtime", True)
    except Exception as e:
        check("C8.6 Evaluator Runtime", False, str(e))

    # C8.7
    try:
        from core.arena.metrics import MetricComputer, PerformanceProfileBuilder
        mc = MetricComputer()
        assert hasattr(mc, "compute")
        check("C8.7 Metric Engine and Profiles", True)
    except Exception as e:
        check("C8.7 Metric Engine and Profiles", False, str(e))

    # C8.8
    try:
        from core.arena.regressions import (
            RegressionDetector, CapabilityProfiler, FailureAnalyzer,
        )
        fa = FailureAnalyzer()
        assert hasattr(fa, "analyze_run")
        check("C8.8 Regression and Analysis", True)
    except Exception as e:
        check("C8.8 Regression and Analysis", False, str(e))

    # C8.9
    try:
        from sdk.agent.interfaces.arena import ArenaSDK, SDKArenaResult
        from core.api.routers.arena import router
        assert len(router.routes) >= 7
        from sdk.agent.sdk import DSRTAgentSDK
        import dataclasses
        assert "arena" in {f.name for f in dataclasses.fields(DSRTAgentSDK)}
        check("C8.9 SDK and API", True)
    except Exception as e:
        check("C8.9 SDK and API", False, str(e))

    # C8.10
    try:
        from core.arena.integration import ArenaOrchestratorHook, ArenaVerificationHook
        hook = ArenaVerificationHook()
        m = hook.ingest_verification(
            arena_run_id="a", verification_run_id="v",
            verification_status="PASSED", checks=[],
        )
        assert len(m) >= 1
        check("C8.10 C5/C6/C7 Integration", True)
    except Exception as e:
        check("C8.10 C5/C6/C7 Integration", False, str(e))

    # Summary
    print("\n" + "=" * 60)
    print("DSRT CORE - PHASE C8 CERTIFICATION")
    print("=" * 60)

    passed = sum(1 for _, ok, _ in checks if ok)
    failed = sum(1 for _, ok, _ in checks if not ok)

    for name, ok, detail in checks:
        icon = "[+]" if ok else "[!]"
        status = "PASS" if ok else "FAIL"
        line = f"  {icon} {status}  {name}"
        if detail:
            line += f" -- {detail}"
        print(line)

    print(f"\n  Total: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed > 0:
        print("\n  C8 CERTIFICATION FAILED")
        return False
    else:
        print("\n  C8 PHASE CERTIFIED COMPLETE")
        return True


if __name__ == "__main__":
    success = verify_c8()
    sys.exit(0 if success else 1)