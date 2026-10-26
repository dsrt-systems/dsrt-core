"""
ExperimentController — Top-level lifecycle manager for paired (and
multi-configuration) comparison experiments.

Responsibilities:
1. Accept experiment requests
2. Validate permissions and budget
3. Build an immutable TaskSnapshot
4. Create the Experiment and ExperimentRun DB records
5. Create isolated run contexts via RunIsolationManager
6. Delegate execution to RunCoordinator
7. Persist outcomes
8. Transition experiment state machine
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from core.execution.experiments.coordinator import (
    RunCoordinator,
    RunExecutor,
    RunOutcome,
    RunStatus,
)
from core.execution.experiments.isolation import (
    IsolatedRunContext,
    RunIsolationManager,
)
from core.execution.experiments.snapshot import TaskSnapshot, TaskSnapshotBuilder

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / result schemas
# ---------------------------------------------------------------------------

class ExperimentConfiguration(BaseModel):
    """One execution configuration in the experiment."""

    configuration_id: str = Field(default_factory=lambda: str(uuid4()))
    label: str = ""
    protocol_type: str = ""  # "DIRECT", "AMPLIFIED", custom
    model_provider: str = ""
    model_id: str = ""
    model_version: str | None = None
    inference_params: dict[str, Any] = Field(default_factory=dict)
    budget_limit_usd: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExperimentBudget(BaseModel):
    """Budget envelope for the entire experiment."""

    total_budget_usd: float | None = None
    per_run_budget_usd: float | None = None
    max_duration_seconds: int | None = None


class ExperimentRequest(BaseModel):
    """
    Top-level request to create and optionally execute an experiment.

    ``configurations`` is a list, not a fixed pair, to support
    multi-configuration experiments from the start.
    """

    workspace_id: str
    task_id: str
    task_prompt: str = ""
    system_instructions: str = ""
    configurations: list[ExperimentConfiguration] = Field(default_factory=list)
    evaluation_suite_id: str | None = None
    budget: ExperimentBudget = Field(default_factory=ExperimentBudget)
    isolation_required: bool = True
    concurrent: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExperimentResult(BaseModel):
    """Aggregated result of a completed experiment."""

    experiment_id: str
    snapshot_id: str
    status: str  # COMPLETED, PARTIALLY_COMPLETED, FAILED, CANCELLED
    run_outcomes: list[dict[str, Any]] = Field(default_factory=list)
    total_cost_usd: float = 0.0
    total_duration_ms: int = 0
    completed_runs: int = 0
    failed_runs: int = 0
    cancelled_runs: int = 0
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Experiment state machine
# ---------------------------------------------------------------------------

class ExperimentState:
    """Lightweight experiment state tracker."""

    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    SNAPSHOT_CREATED = "SNAPSHOT_CREATED"
    RUNS_CREATED = "RUNS_CREATED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    _TRANSITIONS: dict[str, list[str]] = {
        CREATED: [VALIDATING, CANCELLED],
        VALIDATING: [SNAPSHOT_CREATED, FAILED, CANCELLED],
        SNAPSHOT_CREATED: [RUNS_CREATED, FAILED, CANCELLED],
        RUNS_CREATED: [EXECUTING, FAILED, CANCELLED],
        EXECUTING: [COMPLETED, PARTIALLY_COMPLETED, FAILED, CANCELLED],
    }

    def __init__(self) -> None:
        self.current = self.CREATED
        self.history: list[tuple[str, str, datetime]] = []

    def transition(self, target: str) -> None:
        allowed = self._TRANSITIONS.get(self.current, [])
        if target not in allowed:
            raise ValueError(
                f"Invalid experiment state transition: "
                f"{self.current} → {target}. "
                f"Allowed: {allowed}"
            )
        prev = self.current
        self.current = target
        self.history.append((prev, target, datetime.now(timezone.utc)))


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class ExperimentController:
    """
    Manages the full lifecycle of a comparison experiment.

    Designed for dependency injection: pass ``executors`` (protocol_type →
    RunExecutor) and optional ``persistence`` callbacks.
    """

    def __init__(
        self,
        *,
        executors: dict[str, RunExecutor],
    ) -> None:
        self._executors = executors

    # -- public API ---------------------------------------------------------

    async def create_and_execute(
        self,
        request: ExperimentRequest,
    ) -> ExperimentResult:
        """
        Full experiment lifecycle: validate → snapshot → isolate →
        execute → collect.
        """
        experiment_id = str(uuid4())
        state = ExperimentState()

        # 1. Validate
        state.transition(ExperimentState.VALIDATING)
        self._validate(request)

        # 2. Build snapshot
        state.transition(ExperimentState.SNAPSHOT_CREATED)
        snapshot = self._build_snapshot(experiment_id, request)

        # 3. Create isolated contexts
        state.transition(ExperimentState.RUNS_CREATED)
        isolation = RunIsolationManager(snapshot)
        contexts = self._create_run_contexts(isolation, request)

        # 4. Execute
        state.transition(ExperimentState.EXECUTING)
        coordinator = RunCoordinator(
            executors=self._executors,
            concurrent=request.concurrent,
            experiment_budget_usd=(
                request.budget.total_budget_usd
                if request.budget
                else None
            ),
        )

        outcomes = await coordinator.execute_all(contexts)

        # 5. Determine final state
        completed = sum(
            1 for o in outcomes if o.status == RunStatus.COMPLETED
        )
        failed = sum(
            1 for o in outcomes if o.status == RunStatus.FAILED
        )
        cancelled = sum(
            1 for o in outcomes
            if o.status in (RunStatus.CANCELLED, RunStatus.BUDGET_EXCEEDED)
        )

        if completed == len(outcomes):
            state.transition(ExperimentState.COMPLETED)
            final_status = ExperimentState.COMPLETED
        elif completed > 0:
            state.transition(ExperimentState.PARTIALLY_COMPLETED)
            final_status = ExperimentState.PARTIALLY_COMPLETED
        elif cancelled == len(outcomes):
            state.transition(ExperimentState.CANCELLED)
            final_status = ExperimentState.CANCELLED
        else:
            state.transition(ExperimentState.FAILED)
            final_status = ExperimentState.FAILED

        # 6. Build result
        return ExperimentResult(
            experiment_id=experiment_id,
            snapshot_id=snapshot.snapshot_id,
            status=final_status,
            run_outcomes=[self._outcome_to_dict(o) for o in outcomes],
            total_cost_usd=coordinator.total_cost_usd,
            total_duration_ms=sum(o.duration_ms for o in outcomes),
            completed_runs=completed,
            failed_runs=failed,
            cancelled_runs=cancelled,
            completed_at=datetime.now(timezone.utc),
            metadata={
                "state_history": [
                    {"from": f, "to": t, "at": ts.isoformat()}
                    for f, t, ts in state.history
                ],
            },
        )

    async def cancel(self, coordinator: RunCoordinator) -> None:
        """Forward cancellation to the coordinator."""
        coordinator.cancel()

    # -- internal -----------------------------------------------------------

    def _validate(self, request: ExperimentRequest) -> None:
        if not request.workspace_id:
            raise ValueError("workspace_id is required.")
        if not request.task_id:
            raise ValueError("task_id is required.")
        if len(request.configurations) < 2:
            raise ValueError(
                "An experiment requires at least two configurations."
            )
        for cfg in request.configurations:
            if not cfg.protocol_type:
                raise ValueError(
                    f"Configuration '{cfg.label or cfg.configuration_id}' "
                    f"is missing protocol_type."
                )
            if cfg.protocol_type not in self._executors:
                raise ValueError(
                    f"No executor registered for protocol "
                    f"'{cfg.protocol_type}'. "
                    f"Available: {list(self._executors.keys())}"
                )

    def _build_snapshot(
        self,
        experiment_id: str,
        request: ExperimentRequest,
    ) -> TaskSnapshot:
        # Use the first configuration's model info for the shared snapshot.
        # Each isolated context can override model params from its config.
        first_cfg = request.configurations[0]

        builder = TaskSnapshotBuilder()
        builder.set_identifiers(
            experiment_id=experiment_id,
            workspace_id=request.workspace_id,
            task_id=request.task_id,
        )
        builder.set_context(
            system_instructions=request.system_instructions,
            task_prompt=request.task_prompt,
        )
        builder.set_model(
            provider=first_cfg.model_provider,
            model_id=first_cfg.model_id,
            model_version=first_cfg.model_version,
            inference_params=first_cfg.inference_params,
        )
        if request.evaluation_suite_id:
            builder.set_evaluation(
                evaluation_suite_id=request.evaluation_suite_id,
            )
        return builder.build()

    def _create_run_contexts(
        self,
        isolation: RunIsolationManager,
        request: ExperimentRequest,
    ) -> list[IsolatedRunContext]:
        contexts: list[IsolatedRunContext] = []
        for cfg in request.configurations:
            per_run_budget = (
                cfg.budget_limit_usd
                or (request.budget.per_run_budget_usd if request.budget else None)
            )
            ctx = isolation.create_isolated_context(
                configuration_id=cfg.configuration_id,
                protocol_type=cfg.protocol_type,
                budget_limit_usd=per_run_budget,
            )
            # Override model identity per configuration
            ctx.model_provider = cfg.model_provider
            ctx.model_id = cfg.model_id
            ctx.model_version = cfg.model_version
            ctx.inference_params = dict(cfg.inference_params)
            contexts.append(ctx)
        return contexts

    @staticmethod
    def _outcome_to_dict(outcome: RunOutcome) -> dict[str, Any]:
        return {
            "run_id": outcome.run_id,
            "execution_id": outcome.execution_id,
            "configuration_id": outcome.configuration_id,
            "protocol_type": outcome.protocol_type,
            "status": outcome.status.value,
            "output": outcome.output,
            "error_message": outcome.error_message,
            "error_type": outcome.error_type,
            "input_tokens": outcome.input_tokens,
            "output_tokens": outcome.output_tokens,
            "total_cost_usd": outcome.total_cost_usd,
            "duration_ms": outcome.duration_ms,
            "step_count": outcome.step_count,
            "trace_id": outcome.trace_id,
            "artifact_refs": outcome.artifact_refs,
            "started_at": (
                outcome.started_at.isoformat() if outcome.started_at else None
            ),
            "completed_at": (
                outcome.completed_at.isoformat()
                if outcome.completed_at
                else None
            ),
        }