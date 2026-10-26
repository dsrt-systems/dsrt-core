"""
C10.5 — Paired Experiment Controller tests.

Covers:
1. TaskSnapshot — build, freeze, integrity verification
2. RunIsolationManager — context creation, isolation guarantees
3. RunCoordinator — sequential execution, cancellation, budget enforcement
4. ExperimentController — full lifecycle with two configurations
5. PairedComparisonProtocol — protocol adapter integration
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from core.execution.experiments.snapshot import (
    TaskSnapshot,
    TaskSnapshotBuilder,
)
from core.execution.experiments.isolation import (
    IsolatedRunContext,
    RunIsolationManager,
)
from core.execution.experiments.coordinator import (
    RunCoordinator,
    RunOutcome,
    RunStatus,
)
from core.execution.experiments.experiment_controller import (
    ExperimentConfiguration,
    ExperimentController,
    ExperimentRequest,
    ExperimentResult,
    ExperimentState,
    ExperimentBudget,
)
from core.execution.protocols.paired import PairedComparisonProtocol


# =====================================================================
# Helpers
# =====================================================================

def _make_snapshot(experiment_id: str = "exp-1") -> TaskSnapshot:
    builder = TaskSnapshotBuilder()
    builder.set_identifiers(
        experiment_id=experiment_id,
        workspace_id="ws-1",
        task_id="task-1",
    )
    builder.set_context(
        system_instructions="You are a helpful assistant.",
        task_prompt="Explain quantum computing in 100 words.",
    )
    builder.set_model(
        provider="openai",
        model_id="gpt-4o",
        model_version="2024-05-13",
        inference_params={"temperature": 0.7, "max_tokens": 500},
    )
    builder.set_environment(
        initial_file_hashes={"main.py": "abc123"},
        environment_type="sandbox",
    )
    builder.set_evaluation(
        evaluation_suite_id="eval-suite-1",
        evaluator_version="1.0.0",
    )
    return builder.build()


def _make_success_executor(
    output: str = "result",
    cost: float = 0.01,
) -> AsyncMock:
    """Returns an executor whose execute_run produces a COMPLETED outcome."""

    async def _run(context: IsolatedRunContext) -> RunOutcome:
        return RunOutcome(
            run_id=context.run_id,
            execution_id=context.execution_id,
            configuration_id=context.configuration_id,
            protocol_type=context.protocol_type,
            status=RunStatus.COMPLETED,
            output=output,
            input_tokens=100,
            output_tokens=50,
            total_cost_usd=cost,
            duration_ms=200,
            step_count=1,
            trace_id=context.trace_id,
        )

    executor = AsyncMock()
    executor.execute_run = AsyncMock(side_effect=_run)
    return executor


def _make_failing_executor(error: str = "model error") -> AsyncMock:
    async def _run(context: IsolatedRunContext) -> RunOutcome:
        return RunOutcome(
            run_id=context.run_id,
            execution_id=context.execution_id,
            configuration_id=context.configuration_id,
            protocol_type=context.protocol_type,
            status=RunStatus.FAILED,
            error_message=error,
            error_type="ProviderError",
            total_cost_usd=0.001,
            duration_ms=50,
            trace_id=context.trace_id,
        )

    executor = AsyncMock()
    executor.execute_run = AsyncMock(side_effect=_run)
    return executor


# =====================================================================
# 1. TaskSnapshot
# =====================================================================

class TestTaskSnapshot:
    def test_build_and_freeze(self):
        snapshot = _make_snapshot()
        assert snapshot.frozen is True
        assert snapshot.content_hash != ""
        assert len(snapshot.content_hash) == 64  # SHA-256 hex digest

    def test_integrity_passes_after_freeze(self):
        snapshot = _make_snapshot()
        assert snapshot.verify_integrity() is True

    def test_integrity_fails_after_mutation(self):
        snapshot = _make_snapshot()
        snapshot.context.task_prompt = "Modified prompt"
        assert snapshot.verify_integrity() is False

    def test_unfrozen_snapshot_fails_integrity(self):
        snapshot = TaskSnapshot(workspace_id="ws-1", task_id="task-1")
        assert snapshot.verify_integrity() is False

    def test_deterministic_hash(self):
        s1 = _make_snapshot("exp-a")
        s2 = _make_snapshot("exp-a")
        # Same inputs → same hash (experiment_id is not in the hash payload,
        # but workspace_id and task_id are)
        assert s1.content_hash == s2.content_hash

    def test_different_inputs_different_hash(self):
        s1 = _make_snapshot("exp-1")
        builder = TaskSnapshotBuilder()
        builder.set_identifiers(
            experiment_id="exp-2",
            workspace_id="ws-1",
            task_id="task-1",
        )
        builder.set_context(task_prompt="Different prompt")
        builder.set_model(provider="openai", model_id="gpt-4o")
        s2 = builder.build()
        assert s1.content_hash != s2.content_hash


# =====================================================================
# 2. RunIsolationManager
# =====================================================================

class TestRunIsolationManager:
    def test_creates_isolated_contexts(self):
        snapshot = _make_snapshot()
        mgr = RunIsolationManager(snapshot)

        ctx_a = mgr.create_isolated_context(
            configuration_id="cfg-direct",
            protocol_type="DIRECT",
        )
        ctx_b = mgr.create_isolated_context(
            configuration_id="cfg-amplified",
            protocol_type="AMPLIFIED",
        )

        # Different execution IDs
        assert ctx_a.execution_id != ctx_b.execution_id
        # Different run IDs
        assert ctx_a.run_id != ctx_b.run_id
        # Different trace IDs
        assert ctx_a.trace_id != ctx_b.trace_id
        # Different artifact namespaces
        assert ctx_a.artifact_namespace != ctx_b.artifact_namespace
        # Same snapshot reference
        assert ctx_a.snapshot_id == ctx_b.snapshot_id
        assert ctx_a.snapshot_hash == ctx_b.snapshot_hash
        # Same task data from snapshot
        assert ctx_a.task_prompt == ctx_b.task_prompt
        assert ctx_a.model_id == ctx_b.model_id

    def test_rejects_unfrozen_snapshot(self):
        snapshot = TaskSnapshot(workspace_id="ws-1")
        with pytest.raises(ValueError, match="unfrozen"):
            RunIsolationManager(snapshot)

    def test_rejects_tampered_snapshot(self):
        snapshot = _make_snapshot()
        snapshot.context.task_prompt = "tampered"
        with pytest.raises(ValueError, match="integrity"):
            RunIsolationManager(snapshot)

    def test_budget_tracking(self):
        snapshot = _make_snapshot()
        mgr = RunIsolationManager(snapshot)
        ctx = mgr.create_isolated_context(
            configuration_id="cfg-1",
            protocol_type="DIRECT",
            budget_limit_usd=1.00,
        )
        assert ctx.budget_remaining == 1.00
        assert ctx.is_budget_exceeded() is False

        ctx.add_cost(0.60)
        assert ctx.budget_remaining == pytest.approx(0.40)
        assert ctx.is_budget_exceeded() is False

        ctx.add_cost(0.50)
        assert ctx.is_budget_exceeded() is True

    def test_tracks_created_run_ids(self):
        snapshot = _make_snapshot()
        mgr = RunIsolationManager(snapshot)
        ctx1 = mgr.create_isolated_context(
            configuration_id="c1", protocol_type="DIRECT"
        )
        ctx2 = mgr.create_isolated_context(
            configuration_id="c2", protocol_type="AMPLIFIED"
        )
        assert len(mgr.created_run_ids) == 2
        assert ctx1.run_id in mgr.created_run_ids
        assert ctx2.run_id in mgr.created_run_ids


# =====================================================================
# 3. RunCoordinator
# =====================================================================

class TestRunCoordinator:
    @pytest.mark.asyncio
    async def test_sequential_both_succeed(self):
        direct_exec = _make_success_executor("direct output", 0.01)
        amplified_exec = _make_success_executor("amplified output", 0.05)

        coordinator = RunCoordinator(
            executors={"DIRECT": direct_exec, "AMPLIFIED": amplified_exec},
        )

        snapshot = _make_snapshot()
        mgr = RunIsolationManager(snapshot)
        ctx_a = mgr.create_isolated_context(
            configuration_id="cfg-d", protocol_type="DIRECT"
        )
        ctx_b = mgr.create_isolated_context(
            configuration_id="cfg-a", protocol_type="AMPLIFIED"
        )

        outcomes = await coordinator.execute_all([ctx_a, ctx_b])

        assert len(outcomes) == 2
        assert outcomes[0].status == RunStatus.COMPLETED
        assert outcomes[0].output == "direct output"
        assert outcomes[1].status == RunStatus.COMPLETED
        assert outcomes[1].output == "amplified output"
        assert coordinator.total_cost_usd == pytest.approx(0.06)

    @pytest.mark.asyncio
    async def test_one_run_fails(self):
        direct_exec = _make_success_executor("ok", 0.01)
        amplified_exec = _make_failing_executor("timeout")

        coordinator = RunCoordinator(
            executors={"DIRECT": direct_exec, "AMPLIFIED": amplified_exec},
        )

        snapshot = _make_snapshot()
        mgr = RunIsolationManager(snapshot)
        ctx_a = mgr.create_isolated_context(
            configuration_id="c1", protocol_type="DIRECT"
        )
        ctx_b = mgr.create_isolated_context(
            configuration_id="c2", protocol_type="AMPLIFIED"
        )

        outcomes = await coordinator.execute_all([ctx_a, ctx_b])

        assert outcomes[0].status == RunStatus.COMPLETED
        assert outcomes[1].status == RunStatus.FAILED
        assert outcomes[1].error_message == "timeout"

    @pytest.mark.asyncio
    async def test_cancellation(self):
        direct_exec = _make_success_executor("ok", 0.01)
        amplified_exec = _make_success_executor("ok", 0.01)

        coordinator = RunCoordinator(
            executors={"DIRECT": direct_exec, "AMPLIFIED": amplified_exec},
        )
        coordinator.cancel()  # cancel before execution

        snapshot = _make_snapshot()
        mgr = RunIsolationManager(snapshot)
        ctx_a = mgr.create_isolated_context(
            configuration_id="c1", protocol_type="DIRECT"
        )
        ctx_b = mgr.create_isolated_context(
            configuration_id="c2", protocol_type="AMPLIFIED"
        )

        outcomes = await coordinator.execute_all([ctx_a, ctx_b])

        assert all(o.status == RunStatus.CANCELLED for o in outcomes)
        assert coordinator.total_cost_usd == 0.0

    @pytest.mark.asyncio
    async def test_experiment_budget_enforcement(self):
        # First run costs 0.50, second should be blocked by 0.60 budget
        expensive_exec = _make_success_executor("expensive", 0.50)
        cheap_exec = _make_success_executor("cheap", 0.01)

        coordinator = RunCoordinator(
            executors={"DIRECT": expensive_exec, "AMPLIFIED": cheap_exec},
            experiment_budget_usd=0.60,
        )

        snapshot = _make_snapshot()
        mgr = RunIsolationManager(snapshot)
        ctx_a = mgr.create_isolated_context(
            configuration_id="c1", protocol_type="DIRECT"
        )
        ctx_b = mgr.create_isolated_context(
            configuration_id="c2", protocol_type="DIRECT"
        )
        ctx_c = mgr.create_isolated_context(
            configuration_id="c3", protocol_type="AMPLIFIED"
        )

        outcomes = await coordinator.execute_all([ctx_a, ctx_b, ctx_c])

        assert outcomes[0].status == RunStatus.COMPLETED
        # After first run: cost = 0.50. Second run (DIRECT, cost 0.50):
        # 0.50 < 0.60, so it runs. After: cost = 1.00. Third is blocked.
        assert outcomes[1].status == RunStatus.COMPLETED
        assert outcomes[2].status == RunStatus.BUDGET_EXCEEDED

    @pytest.mark.asyncio
    async def test_missing_executor(self):
        coordinator = RunCoordinator(executors={"DIRECT": _make_success_executor()})

        snapshot = _make_snapshot()
        mgr = RunIsolationManager(snapshot)
        ctx = mgr.create_isolated_context(
            configuration_id="c1", protocol_type="UNKNOWN_PROTOCOL"
        )

        outcomes = await coordinator.execute_all([ctx])

        assert outcomes[0].status == RunStatus.FAILED
        assert "No executor registered" in (outcomes[0].error_message or "")

    @pytest.mark.asyncio
    async def test_executor_raises_exception(self):
        bad_executor = AsyncMock()
        bad_executor.execute_run = AsyncMock(
            side_effect=RuntimeError("unexpected crash")
        )

        coordinator = RunCoordinator(executors={"DIRECT": bad_executor})

        snapshot = _make_snapshot()
        mgr = RunIsolationManager(snapshot)
        ctx = mgr.create_isolated_context(
            configuration_id="c1", protocol_type="DIRECT"
        )

        outcomes = await coordinator.execute_all([ctx])

        assert outcomes[0].status == RunStatus.FAILED
        assert "unexpected crash" in (outcomes[0].error_message or "")
        assert outcomes[0].error_type == "RuntimeError"


# =====================================================================
# 4. ExperimentState
# =====================================================================

class TestExperimentState:
    def test_valid_transitions(self):
        state = ExperimentState()
        assert state.current == ExperimentState.CREATED
        state.transition(ExperimentState.VALIDATING)
        state.transition(ExperimentState.SNAPSHOT_CREATED)
        state.transition(ExperimentState.RUNS_CREATED)
        state.transition(ExperimentState.EXECUTING)
        state.transition(ExperimentState.COMPLETED)
        assert state.current == ExperimentState.COMPLETED
        assert len(state.history) == 5

    def test_invalid_transition_raises(self):
        state = ExperimentState()
        with pytest.raises(ValueError, match="Invalid experiment state"):
            state.transition(ExperimentState.EXECUTING)

    def test_cancellation_from_created(self):
        state = ExperimentState()
        state.transition(ExperimentState.CANCELLED)
        assert state.current == ExperimentState.CANCELLED


# =====================================================================
# 5. ExperimentController
# =====================================================================

class TestExperimentController:
    @pytest.mark.asyncio
    async def test_successful_experiment(self):
        direct_exec = _make_success_executor("direct result", 0.02)
        amplified_exec = _make_success_executor("amplified result", 0.08)

        controller = ExperimentController(
            executors={"DIRECT": direct_exec, "AMPLIFIED": amplified_exec},
        )

        request = ExperimentRequest(
            workspace_id="ws-1",
            task_id="task-1",
            task_prompt="Explain quantum computing.",
            system_instructions="Be concise.",
            configurations=[
                ExperimentConfiguration(
                    label="Direct Baseline",
                    protocol_type="DIRECT",
                    model_provider="openai",
                    model_id="gpt-4o",
                ),
                ExperimentConfiguration(
                    label="DSRT Amplified",
                    protocol_type="AMPLIFIED",
                    model_provider="openai",
                    model_id="gpt-4o",
                ),
            ],
        )

        result = await controller.create_and_execute(request)

        assert result.status == "COMPLETED"
        assert result.completed_runs == 2
        assert result.failed_runs == 0
        assert result.cancelled_runs == 0
        assert result.total_cost_usd == pytest.approx(0.10)
        assert len(result.run_outcomes) == 2
        assert result.run_outcomes[0]["output"] == "direct result"
        assert result.run_outcomes[1]["output"] == "amplified result"
        assert result.snapshot_id != ""
        assert result.experiment_id != ""

    @pytest.mark.asyncio
    async def test_partial_failure(self):
        direct_exec = _make_success_executor("ok", 0.01)
        amplified_exec = _make_failing_executor("model unavailable")

        controller = ExperimentController(
            executors={"DIRECT": direct_exec, "AMPLIFIED": amplified_exec},
        )

        request = ExperimentRequest(
            workspace_id="ws-1",
            task_id="task-1",
            task_prompt="Test",
            configurations=[
                ExperimentConfiguration(
                    protocol_type="DIRECT",
                    model_provider="openai",
                    model_id="gpt-4o",
                ),
                ExperimentConfiguration(
                    protocol_type="AMPLIFIED",
                    model_provider="openai",
                    model_id="gpt-4o",
                ),
            ],
        )

        result = await controller.create_and_execute(request)

        assert result.status == "PARTIALLY_COMPLETED"
        assert result.completed_runs == 1
        assert result.failed_runs == 1

    @pytest.mark.asyncio
    async def test_all_fail(self):
        failing = _make_failing_executor("error")

        controller = ExperimentController(
            executors={"DIRECT": failing, "AMPLIFIED": failing},
        )

        request = ExperimentRequest(
            workspace_id="ws-1",
            task_id="task-1",
            task_prompt="Test",
            configurations=[
                ExperimentConfiguration(
                    protocol_type="DIRECT",
                    model_provider="openai",
                    model_id="gpt-4o",
                ),
                ExperimentConfiguration(
                    protocol_type="AMPLIFIED",
                    model_provider="openai",
                    model_id="gpt-4o",
                ),
            ],
        )

        result = await controller.create_and_execute(request)

        assert result.status == "FAILED"
        assert result.completed_runs == 0
        assert result.failed_runs == 2

    @pytest.mark.asyncio
    async def test_validation_requires_two_configs(self):
        controller = ExperimentController(
            executors={"DIRECT": _make_success_executor()},
        )

        request = ExperimentRequest(
            workspace_id="ws-1",
            task_id="task-1",
            task_prompt="Test",
            configurations=[
                ExperimentConfiguration(
                    protocol_type="DIRECT",
                    model_provider="openai",
                    model_id="gpt-4o",
                ),
            ],
        )

        with pytest.raises(ValueError, match="at least two"):
            await controller.create_and_execute(request)

    @pytest.mark.asyncio
    async def test_validation_requires_registered_executor(self):
        controller = ExperimentController(
            executors={"DIRECT": _make_success_executor()},
        )

        request = ExperimentRequest(
            workspace_id="ws-1",
            task_id="task-1",
            task_prompt="Test",
            configurations=[
                ExperimentConfiguration(
                    protocol_type="DIRECT",
                    model_provider="openai",
                    model_id="gpt-4o",
                ),
                ExperimentConfiguration(
                    protocol_type="UNREGISTERED",
                    model_provider="openai",
                    model_id="gpt-4o",
                ),
            ],
        )

        with pytest.raises(ValueError, match="No executor registered"):
            await controller.create_and_execute(request)

    @pytest.mark.asyncio
    async def test_multi_configuration_experiment(self):
        """Three configurations — spec requires extensibility beyond pairs."""
        exec_a = _make_success_executor("A", 0.01)
        exec_b = _make_success_executor("B", 0.02)

        controller = ExperimentController(
            executors={"DIRECT": exec_a, "AMPLIFIED": exec_b},
        )

        request = ExperimentRequest(
            workspace_id="ws-1",
            task_id="task-1",
            task_prompt="Compare three",
            configurations=[
                ExperimentConfiguration(
                    label="Direct A",
                    protocol_type="DIRECT",
                    model_provider="openai",
                    model_id="gpt-4o",
                ),
                ExperimentConfiguration(
                    label="Amplified B",
                    protocol_type="AMPLIFIED",
                    model_provider="openai",
                    model_id="gpt-4o",
                ),
                ExperimentConfiguration(
                    label="Direct C (different params)",
                    protocol_type="DIRECT",
                    model_provider="openai",
                    model_id="gpt-4o-mini",
                    inference_params={"temperature": 0.0},
                ),
            ],
        )

        result = await controller.create_and_execute(request)

        assert result.status == "COMPLETED"
        assert result.completed_runs == 3
        assert len(result.run_outcomes) == 3


# =====================================================================
# 6. PairedComparisonProtocol
# =====================================================================

class TestPairedComparisonProtocol:
    @pytest.mark.asyncio
    async def test_validate_valid_request(self):
        protocol = PairedComparisonProtocol(
            executors={
                "DIRECT": _make_success_executor(),
                "AMPLIFIED": _make_success_executor(),
            },
        )

        request = {
            "workspace_id": "ws-1",
            "task_id": "task-1",
            "config": {
                "configurations": [
                    {"protocol_type": "DIRECT", "model_provider": "openai", "model_id": "gpt-4o"},
                    {"protocol_type": "AMPLIFIED", "model_provider": "openai", "model_id": "gpt-4o"},
                ],
                "task_prompt": "Test",
            },
        }

        result = await protocol.validate(request)
        assert result["valid"] is True
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_validate_missing_configs(self):
        protocol = PairedComparisonProtocol(executors={})

        request = {
            "workspace_id": "ws-1",
            "task_id": "task-1",
            "config": {"configurations": []},
        }

        result = await protocol.validate(request)
        assert result["valid"] is False
        assert any("two configurations" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        protocol = PairedComparisonProtocol(
            executors={
                "DIRECT": _make_success_executor("direct", 0.01),
                "AMPLIFIED": _make_success_executor("amplified", 0.05),
            },
        )

        request = {
            "workspace_id": "ws-1",
            "task_id": "task-1",
            "execution_id": "exec-1",
            "config": {
                "task_prompt": "Explain X",
                "system_instructions": "Be brief",
                "configurations": [
                    {"protocol_type": "DIRECT", "model_provider": "openai", "model_id": "gpt-4o"},
                    {"protocol_type": "AMPLIFIED", "model_provider": "openai", "model_id": "gpt-4o"},
                ],
            },
        }

        # validate
        val = await protocol.validate(request)
        assert val["valid"] is True

        # prepare
        prepared = await protocol.prepare(request)
        assert prepared["protocol"] == "paired_comparison"
        assert prepared["experiment_request"] is not None

        # execute
        result = await protocol.execute(prepared)
        assert result["success"] is True
        assert result["status"] == "COMPLETED"
        assert result["completed_runs"] == 2
        assert result["total_cost_usd"] == pytest.approx(0.06)
        assert len(result["run_outcomes"]) == 2

        # finalize
        fin = await protocol.finalize("exec-1")
        assert fin["finalized"] is True