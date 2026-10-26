"""
Arena Run Manager (C8 §13-14, §54, §67).

Manages the lifecycle of individual Arena runs:
  CREATED → QUEUED → PROVISIONING_WORLD → INITIALIZING →
  RUNNING → VERIFYING → EVALUATING → COMPLETED

Also handles failure paths:
  RUNNING → FAILED
  EVALUATING → EVALUATION_FAILED
  Any → CANCELLED

Key principles:
  - Run lifecycle is deterministic (C8 §14)
  - Configuration hash ensures reproducibility (C8 §43, §54)
  - Every run produces a trajectory (C8 §16-18)
  - Evaluation is separate from execution (C8 §57)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import ArenaRunStatus, EventType

from core.api.errors.exceptions import NotFoundError, ValidationError
from core.kernel.kernel import ExecutionKernel
from core.observability.logging import get_logger
from core.storage.models.arena import ArenaRunORM


logger = get_logger("dsrt.arena.runs")


# Valid lifecycle transitions (C8 §14)
_VALID_TRANSITIONS: dict[str, set[str]] = {
    ArenaRunStatus.CREATED.value: {
        ArenaRunStatus.QUEUED.value,
        ArenaRunStatus.CANCELLED.value,
    },
    ArenaRunStatus.QUEUED.value: {
        ArenaRunStatus.PROVISIONING_WORLD.value,
        ArenaRunStatus.CANCELLED.value,
    },
    ArenaRunStatus.PROVISIONING_WORLD.value: {
        ArenaRunStatus.INITIALIZING.value,
        ArenaRunStatus.FAILED.value,
        ArenaRunStatus.CANCELLED.value,
    },
    ArenaRunStatus.INITIALIZING.value: {
        ArenaRunStatus.RUNNING.value,
        ArenaRunStatus.FAILED.value,
        ArenaRunStatus.CANCELLED.value,
    },
    ArenaRunStatus.RUNNING.value: {
        ArenaRunStatus.VERIFYING.value,
        ArenaRunStatus.FAILED.value,
        ArenaRunStatus.CANCELLED.value,
    },
    ArenaRunStatus.VERIFYING.value: {
        ArenaRunStatus.EVALUATING.value,
        ArenaRunStatus.FAILED.value,
    },
    ArenaRunStatus.EVALUATING.value: {
        ArenaRunStatus.COMPLETED.value,
        ArenaRunStatus.EVALUATION_FAILED.value,
        ArenaRunStatus.FAILED.value,
    },
    # Terminal states
    ArenaRunStatus.COMPLETED.value: set(),
    ArenaRunStatus.FAILED.value: set(),
    ArenaRunStatus.EVALUATION_FAILED.value: set(),
    ArenaRunStatus.CANCELLED.value: set(),
}


class ArenaRunManager:
    """Manages Arena run lifecycle (C8 §13-14).

    Usage:
        mgr = ArenaRunManager(session, kernel)
        run = await mgr.get_run("arn_1")
        await mgr.transition(run.id, ArenaRunStatus.QUEUED)
        await mgr.transition(run.id, ArenaRunStatus.RUNNING)
        await mgr.mark_completed(run.id, execution_id="exe_1")
    """

    def __init__(
        self,
        session: AsyncSession,
        kernel: ExecutionKernel | None = None,
    ) -> None:
        self._session = session
        self._kernel = kernel

    async def transition(
        self,
        run_id: str,
        target_status: ArenaRunStatus | str,
    ) -> ArenaRunORM:
        """Transition a run to a new status (C8 §14).

        Validates the transition against the lifecycle state machine.
        Emits an event for trajectory tracking.

        Raises:
            NotFoundError: If the run doesn't exist.
            ValidationError: If the transition is invalid.
        """
        run = await self.get_run(run_id)
        target = (
            target_status.value
            if isinstance(target_status, ArenaRunStatus)
            else target_status
        )

        # Validate transition
        allowed = _VALID_TRANSITIONS.get(run.status, set())
        if target not in allowed:
            raise ValidationError(
                f"Invalid Arena run transition: '{run.status}' -> '{target}'. "
                f"Allowed: {sorted(allowed)}"
            )

        old_status = run.status
        run.status = target

        # Set timestamps
        now = datetime.now(timezone.utc)
        if target == ArenaRunStatus.RUNNING.value and not run.started_at:
            run.started_at = now
        if target in (
            ArenaRunStatus.COMPLETED.value,
            ArenaRunStatus.FAILED.value,
            ArenaRunStatus.EVALUATION_FAILED.value,
            ArenaRunStatus.CANCELLED.value,
        ):
            run.completed_at = now

        await self._session.flush()

        # Emit event
        event_map = {
            ArenaRunStatus.RUNNING.value: EventType.ARENA_RUN_STARTED,
            ArenaRunStatus.COMPLETED.value: EventType.ARENA_RUN_COMPLETED,
            ArenaRunStatus.FAILED.value: EventType.ARENA_RUN_FAILED,
        }
        event_type = event_map.get(target)
        if event_type and run.execution_id:
            await self._emit_event(
                run.execution_id,
                event_type,
                {
                    "arena_run_id": run_id,
                    "previous_status": old_status,
                    "new_status": target,
                },
            )

        logger.info(
            "arena_run_transition",
            run_id=run_id,
            from_status=old_status,
            to_status=target,
        )

        return run

    async def mark_completed(
        self,
        run_id: str,
        execution_id: str,
    ) -> ArenaRunORM:
        """Mark a run as completed and link it to an execution.

        Convenience method that sets the execution_id and transitions
        through VERIFYING → EVALUATING → COMPLETED.
        """
        run = await self.get_run(run_id)
        run.execution_id = execution_id
        await self._session.flush()

        # Walk through the remaining lifecycle stages
        if run.status == ArenaRunStatus.RUNNING.value:
            await self.transition(run_id, ArenaRunStatus.VERIFYING)
            await self.transition(run_id, ArenaRunStatus.EVALUATING)
            await self.transition(run_id, ArenaRunStatus.COMPLETED)
        elif run.status == ArenaRunStatus.EVALUATING.value:
            await self.transition(run_id, ArenaRunStatus.COMPLETED)

        return await self.get_run(run_id)

    async def mark_failed(
        self,
        run_id: str,
        reason: str = "",
    ) -> ArenaRunORM:
        """Mark a run as failed."""
        run = await self.get_run(run_id)

        if run.status == ArenaRunStatus.EVALUATING.value:
            return await self.transition(
                run_id, ArenaRunStatus.EVALUATION_FAILED,
            )

        # Force to FAILED from any non-terminal state
        if run.status not in (
            ArenaRunStatus.COMPLETED.value,
            ArenaRunStatus.FAILED.value,
            ArenaRunStatus.EVALUATION_FAILED.value,
            ArenaRunStatus.CANCELLED.value,
        ):
            run.status = ArenaRunStatus.FAILED.value
            run.completed_at = datetime.now(timezone.utc)
            run.metadata_json = {
                **(run.metadata_json or {}),
                "failure_reason": reason,
            }
            await self._session.flush()

        return run

    async def get_run(self, run_id: str) -> ArenaRunORM:
        """Get an Arena run by ID."""
        stmt = select(ArenaRunORM).where(ArenaRunORM.id == run_id)
        result = await self._session.execute(stmt)
        run = result.scalar_one_or_none()
        if not run:
            raise NotFoundError(f"Arena run '{run_id}' not found.")
        return run

    async def list_runs(
        self,
        experiment_id: str | None = None,
        benchmark_id: str | None = None,
        status: str | None = None,
        agent_slug: str | None = None,
        limit: int = 50,
    ) -> list[ArenaRunORM]:
        """List Arena runs with optional filters."""
        stmt = select(ArenaRunORM).order_by(
            ArenaRunORM.created_at.desc(),
        )
        if experiment_id:
            stmt = stmt.where(ArenaRunORM.experiment_id == experiment_id)
        if benchmark_id:
            stmt = stmt.where(ArenaRunORM.benchmark_id == benchmark_id)
        if status:
            stmt = stmt.where(ArenaRunORM.status == status)
        if agent_slug:
            stmt = stmt.where(ArenaRunORM.agent_slug == agent_slug)
        stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_runs_by_configuration(
        self,
        configuration_hash: str,
    ) -> list[ArenaRunORM]:
        """Get all runs with the same configuration (C8 §35, §54).

        Used for repeated-run analysis and variance reporting.
        """
        stmt = (
            select(ArenaRunORM)
            .where(ArenaRunORM.configuration_hash == configuration_hash)
            .order_by(ArenaRunORM.repetition.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    def validate_transition(
        self, current: str, target: str,
    ) -> bool:
        """Check if a transition is valid without executing it."""
        allowed = _VALID_TRANSITIONS.get(current, set())
        return target in allowed

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _emit_event(
        self,
        execution_id: str,
        event_type: EventType,
        payload: dict[str, Any],
    ) -> None:
        if not self._kernel:
            return
        try:
            await self._kernel.emit_event(
                execution_id=execution_id,
                event_type=event_type,
                source="dsrt.arena.runs",
                payload=payload,
            )
        except Exception as e:
            logger.warning(
                "arena_run_event_failed",
                execution_id=execution_id,
                error=str(e),
            )