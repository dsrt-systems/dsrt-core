"""
RunCoordinator — Orchestrates the execution of multiple runs within
an experiment.

Responsibilities:
- Launch runs sequentially (concurrent mode available as future extension)
- Monitor each run's progress and budget
- Handle per-run failures without aborting the entire experiment
- Collect RunOutcome objects for every configuration
- Support experiment-level cancellation
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol

from core.execution.experiments.isolation import IsolatedRunContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Run outcome
# ---------------------------------------------------------------------------

class RunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"


@dataclass
class RunOutcome:
    """Result of a single run within an experiment."""

    run_id: str
    execution_id: str
    configuration_id: str
    protocol_type: str
    status: RunStatus = RunStatus.PENDING

    output: str | None = None
    error_message: str | None = None
    error_type: str | None = None

    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_usd: float = 0.0
    duration_ms: int = 0
    step_count: int = 0

    started_at: datetime | None = None
    completed_at: datetime | None = None

    trace_id: str = ""
    artifact_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Run executor contract
# ---------------------------------------------------------------------------

class RunExecutor(Protocol):
    """
    Contract that protocol runtimes implement so the coordinator
    can execute them uniformly.
    """

    async def execute_run(
        self,
        context: IsolatedRunContext,
    ) -> RunOutcome:
        ...


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------

class RunCoordinator:
    """
    Orchestrates multiple runs within one experiment.

    Default mode is sequential execution.  ``concurrent=True`` launches
    all runs simultaneously via ``asyncio.gather``.
    """

    def __init__(
        self,
        *,
        executors: dict[str, RunExecutor],
        concurrent: bool = False,
        experiment_budget_usd: float | None = None,
    ) -> None:
        """
        Parameters
        ----------
        executors
            Map of ``protocol_type`` → ``RunExecutor`` implementation.
        concurrent
            If True, runs execute concurrently; otherwise sequentially.
        experiment_budget_usd
            Total budget for the entire experiment.  Individual run
            budgets are enforced inside each ``IsolatedRunContext``.
        """
        self._executors = executors
        self._concurrent = concurrent
        self._experiment_budget_usd = experiment_budget_usd
        self._cancelled = False
        self._total_cost_usd: float = 0.0
        self._outcomes: list[RunOutcome] = []

    # -- public -------------------------------------------------------------

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    @property
    def total_cost_usd(self) -> float:
        return self._total_cost_usd

    @property
    def outcomes(self) -> list[RunOutcome]:
        return list(self._outcomes)

    def cancel(self) -> None:
        """Signal cancellation for all pending runs."""
        self._cancelled = True
        logger.info("Experiment coordinator received cancellation signal.")

    async def execute_all(
        self,
        contexts: list[IsolatedRunContext],
    ) -> list[RunOutcome]:
        """
        Execute all provided run contexts and return their outcomes.

        If the experiment is cancelled or the experiment-level budget
        is exceeded, remaining runs are marked CANCELLED.
        """
        if self._concurrent:
            return await self._execute_concurrent(contexts)
        return await self._execute_sequential(contexts)

    # -- sequential ---------------------------------------------------------

    async def _execute_sequential(
        self,
        contexts: list[IsolatedRunContext],
    ) -> list[RunOutcome]:
        outcomes: list[RunOutcome] = []

        for ctx in contexts:
            if self._cancelled:
                outcomes.append(self._make_cancelled_outcome(ctx))
                continue

            if self._is_experiment_budget_exceeded():
                logger.warning(
                    "Experiment budget exceeded (%.4f USD). "
                    "Cancelling remaining runs.",
                    self._total_cost_usd,
                )
                outcomes.append(self._make_budget_exceeded_outcome(ctx))
                continue

            outcome = await self._execute_single(ctx)
            outcomes.append(outcome)
            self._total_cost_usd += outcome.total_cost_usd

        self._outcomes = outcomes
        return outcomes

    # -- concurrent ---------------------------------------------------------

    async def _execute_concurrent(
        self,
        contexts: list[IsolatedRunContext],
    ) -> list[RunOutcome]:
        tasks = [self._execute_single(ctx) for ctx in contexts]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        outcomes: list[RunOutcome] = []
        for ctx, result in zip(contexts, results):
            if isinstance(result, BaseException):
                outcome = RunOutcome(
                    run_id=ctx.run_id,
                    execution_id=ctx.execution_id,
                    configuration_id=ctx.configuration_id,
                    protocol_type=ctx.protocol_type,
                    status=RunStatus.FAILED,
                    error_message=str(result),
                    error_type=type(result).__name__,
                )
            else:
                outcome = result
            outcomes.append(outcome)
            self._total_cost_usd += outcome.total_cost_usd

        self._outcomes = outcomes
        return outcomes

    # -- single run ---------------------------------------------------------

    async def _execute_single(
        self,
        ctx: IsolatedRunContext,
    ) -> RunOutcome:
        executor = self._executors.get(ctx.protocol_type)
        if executor is None:
            logger.error(
                "No executor registered for protocol '%s'.", ctx.protocol_type
            )
            return RunOutcome(
                run_id=ctx.run_id,
                execution_id=ctx.execution_id,
                configuration_id=ctx.configuration_id,
                protocol_type=ctx.protocol_type,
                status=RunStatus.FAILED,
                error_message=f"No executor registered for protocol '{ctx.protocol_type}'.",
                error_type="MissingExecutor",
            )

        start = time.perf_counter_ns()
        started_at = datetime.now(timezone.utc)

        try:
            outcome = await executor.execute_run(ctx)
            outcome.started_at = started_at
            outcome.completed_at = datetime.now(timezone.utc)
            elapsed_ms = int((time.perf_counter_ns() - start) / 1_000_000)
            if outcome.duration_ms == 0:
                outcome.duration_ms = elapsed_ms
            return outcome

        except Exception as exc:
            elapsed_ms = int((time.perf_counter_ns() - start) / 1_000_000)
            logger.exception(
                "Run %s failed with unhandled exception.", ctx.run_id
            )
            return RunOutcome(
                run_id=ctx.run_id,
                execution_id=ctx.execution_id,
                configuration_id=ctx.configuration_id,
                protocol_type=ctx.protocol_type,
                status=RunStatus.FAILED,
                error_message=str(exc),
                error_type=type(exc).__name__,
                duration_ms=elapsed_ms,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                trace_id=ctx.trace_id,
            )

    # -- helpers ------------------------------------------------------------

    def _is_experiment_budget_exceeded(self) -> bool:
        if self._experiment_budget_usd is None:
            return False
        return self._total_cost_usd >= self._experiment_budget_usd

    @staticmethod
    def _make_cancelled_outcome(ctx: IsolatedRunContext) -> RunOutcome:
        return RunOutcome(
            run_id=ctx.run_id,
            execution_id=ctx.execution_id,
            configuration_id=ctx.configuration_id,
            protocol_type=ctx.protocol_type,
            status=RunStatus.CANCELLED,
            error_message="Experiment was cancelled before this run started.",
            trace_id=ctx.trace_id,
        )

    @staticmethod
    def _make_budget_exceeded_outcome(ctx: IsolatedRunContext) -> RunOutcome:
        return RunOutcome(
            run_id=ctx.run_id,
            execution_id=ctx.execution_id,
            configuration_id=ctx.configuration_id,
            protocol_type=ctx.protocol_type,
            status=RunStatus.BUDGET_EXCEEDED,
            error_message="Experiment budget exceeded before this run started.",
            trace_id=ctx.trace_id,
        )