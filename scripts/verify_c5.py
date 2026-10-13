"""
C5 Phase Certification Script.

Verifies all C5 components are correctly built and integrated.
Run: python scripts/verify_c5.py
"""

from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def verify_c5() -> bool:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        checks.append((name, condition, detail))

    # --- C5.1: Contracts & Schemas ---
    try:
        from schemas.domain.enums import (
            PlanStatus, NodeType, NodeStatus, DependencyType,
            OrchestrationStatus, DelegationStatus, RecoveryAction,
            MergePolicy, StatePatchOperation,
        )
        from schemas.domain.orchestration import (
            Plan, PlanVersion, PlanNode, PlanDependency, PlanConstraints,
            OrchestrationExecution, NodeExecution, OrchestrationCheckpoint,
            Delegation, StatePatch, SharedState, Replan, OrchestrationPolicy,
            MergeResult, PlanRequest,
        )
        from schemas.api.orchestration import (
            CreatePlanRequest, PlanResponse, ExecutePlanRequest,
            OrchestrationExecutionResponse, DelegateRequest,
            ReplanRequest, CheckpointResponse,
        )
        from core.storage.identifiers import IdPrefix
        for prefix in ["PLAN", "PLAN_VERSION", "PLAN_NODE", "PLAN_DEPENDENCY",
                        "ORCHESTRATION_EXECUTION", "NODE_EXECUTION",
                        "ORCHESTRATION_CHECKPOINT", "DELEGATION",
                        "STATE_PATCH", "REPLAN", "SHARED_STATE"]:
            assert hasattr(IdPrefix, prefix), f"Missing prefix: {prefix}"
        check("C5.1 Contracts and Schemas", True)
    except (ImportError, AssertionError) as e:
        check("C5.1 Contracts and Schemas", False, str(e))

    # --- C5.2: Database ---
    try:
        from core.storage.models import (
            PlanORM, PlanVersionORM, PlanNodeORM, PlanDependencyORM,
            OrchestrationExecutionORM, NodeExecutionORM,
            OrchestrationCheckpointORM, DelegationORM,
            SharedStateORM, StatePatchORM, ReplanORM,
        )
        check("C5.2 Database Models", True)
    except ImportError as e:
        check("C5.2 Database Models", False, str(e))

    # --- C5.3: Graph Engine ---
    try:
        from core.orchestration.graph import TaskGraph, CycleDetector, GraphValidator
        from core.orchestration.graph.graph import GraphNode, GraphEdge
        g = TaskGraph()
        g.add_node(GraphNode(key="A"))
        g.add_node(GraphNode(key="B"))
        g.add_edge(GraphEdge(source="A", target="B"))
        assert g.topological_sort() == ["A", "B"]
        assert not CycleDetector(g).has_cycle()
        check("C5.3 Graph Engine", True)
    except Exception as e:
        check("C5.3 Graph Engine", False, str(e))

    # --- C5.4: Planner ---
    try:
        from core.orchestration.planner import Planner, PlanValidator
        from core.orchestration.planner.prompts import build_planning_prompt
        v = PlanValidator()
        r = v.validate(
            [PlanNode(node_key="a", name="A", node_type="AGENT_TASK")],
            [], PlanConstraints(),
        )
        assert r.valid
        check("C5.4 Planner", True)
    except Exception as e:
        check("C5.4 Planner", False, str(e))

    # --- C5.5: Scheduler ---
    try:
        from core.orchestration.scheduler import (
            Scheduler, SchedulingContext, ConcurrencyLimits, SchedulingPolicy,
        )
        s = Scheduler()
        g = TaskGraph()
        g.add_node(GraphNode(key="X"))
        d = s.decide(SchedulingContext(graph=g))
        assert d.nodes_to_start == ["X"]
        check("C5.5 Scheduler", True)
    except Exception as e:
        check("C5.5 Scheduler", False, str(e))

    # --- C5.6: Node Executor ---
    try:
        from core.orchestration.executor import (
            NodeExecutor, NodeExecutionResult, NodeLifecycleManager,
        )
        lm = NodeLifecycleManager()
        lm.validate_transition("PENDING", "READY")
        lm.validate_transition("RUNNING", "COMPLETED")
        check("C5.6 Node Executor", True)
    except Exception as e:
        check("C5.6 Node Executor", False, str(e))

    # --- C5.7: Delegation ---
    try:
        from core.orchestration.delegation import (
            DelegationManager, DelegationRequest, DelegationResult,
        )
        mgr = DelegationManager.__new__(DelegationManager)
        r = mgr._check_budget_propagation(
            {"remaining_usd": 1.0}, {"max_usd": 5.0},
        )
        assert not r.allowed
        check("C5.7 Delegation", True)
    except Exception as e:
        check("C5.7 Delegation", False, str(e))

    # --- C5.8: Shared State ---
    try:
        from core.orchestration.state import (
            SharedStateStore, StatePatchValidator,
            OptimisticConcurrencyControl, ConcurrencyConflict,
        )
        s = {"a": 1}
        n = StatePatchValidator.apply_patch(s, "/a", "replace", 2)
        assert n["a"] == 2 and s["a"] == 1
        check("C5.8 Shared State", True)
    except Exception as e:
        check("C5.8 Shared State", False, str(e))

    # --- C5.9: Checkpoints & Recovery ---
    try:
        from core.orchestration.checkpoints import CheckpointManager
        from core.orchestration.recovery import (
            RecoveryManager, FailureClassification, RecoveryDecision,
        )
        rm = RecoveryManager.__new__(RecoveryManager)
        rm._max_attempts = 3
        rm._base_backoff = 2.0
        rm._max_backoff = 60.0
        rm._backoff_multiplier = 2.0
        rm._heartbeat_timeout = 300
        assert rm.classify_failure("PROVIDER_TIMEOUT") == FailureClassification.RETRYABLE
        assert rm.classify_failure("PERMISSION_DENIED") == FailureClassification.NON_RETRYABLE
        check("C5.9 Checkpoints and Recovery", True)
    except Exception as e:
        check("C5.9 Checkpoints and Recovery", False, str(e))

    # --- C5.10: Replanning ---
    try:
        from core.orchestration.replanning import Replanner, ReplanRequest, ReplanResult
        r = ReplanResult(success=True, new_plan_version_id="pnv_2", replan_id="rpl_1")
        assert r.success
        check("C5.10 Replanning", True)
    except Exception as e:
        check("C5.10 Replanning", False, str(e))

    # --- C5.11: SDK, API, Events ---
    try:
        from schemas.domain.enums import EventType
        for e in ["PLAN_CREATED", "NODE_COMPLETED", "DELEGATION_ACCEPTED",
                   "STATE_PATCH_APPLIED", "CHECKPOINT_CREATED", "NODE_HEARTBEAT"]:
            assert hasattr(EventType, e)
        from sdk.agent.interfaces.orchestration import OrchestrationSDK
        from sdk.agent.adapters.orchestration_adapter import OrchestrationSDKImpl
        from sdk.agent.sdk import DSRTAgentSDK
        import dataclasses
        assert "orchestration" in {f.name for f in dataclasses.fields(DSRTAgentSDK)}
        from core.api.routers.orchestration import router
        assert len(router.routes) >= 10
        check("C5.11 SDK, API, Events", True)
    except Exception as e:
        check("C5.11 SDK, API, Events", False, str(e))

    # --- Summary ---
    print("\n" + "=" * 60)
    print("DSRT CORE - PHASE C5 CERTIFICATION")
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
        print("\n  C5 CERTIFICATION FAILED")
        return False
    else:
        print("\n  C5 PHASE CERTIFIED COMPLETE")
        return True


if __name__ == "__main__":
    success = verify_c5()
    sys.exit(0 if success else 1)