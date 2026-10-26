"""
Arena ↔ C5 Orchestrator Integration (C8 §66-67).

Captures execution trajectories from C5 orchestration events
and feeds them into the Arena evaluation pipeline.

Architecture:
    C5 Orchestrator completes a node
        ↓
    ArenaOrchestratorHook.capture_node_trajectory()
        ↓
    TrajectoryBuilder normalizes events
        ↓
    TrajectoryStore persists trajectory
        ↓
    Evaluator computes metrics
        ↓
    PerformanceProfile saved
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.arena.metrics.computer import MetricComputer
from core.arena.metrics.profiles import PerformanceProfileBuilder
from core.arena.trajectories.builder import TrajectoryBuilder
from core.arena.trajectories.store import TrajectoryStore
from core.observability.logging import get_logger
from core.repositories.event_repository import EventRepository


logger = get_logger("dsrt.arena.integration.orchestrator")


class ArenaOrchestratorHook:
    """Captures C5 execution data and feeds it into Arena evaluation.

    Usage (called by C5 Orchestrator after execution completes):
        hook = ArenaOrchestratorHook(session)
        await hook.finalize_arena_run(
            arena_run_id="arn_1",
            execution_id="exe_1",
            configuration_hash="abc123",
        )
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._event_repo = EventRepository(session)
        self._trajectory_builder = TrajectoryBuilder(self._event_repo)
        self._trajectory_store = TrajectoryStore(session)
        self._metric_computer = MetricComputer()
        self._profile_builder = PerformanceProfileBuilder(session)

    async def finalize_arena_run(
        self,
        *,
        arena_run_id: str,
        execution_id: str,
        configuration_hash: str = "",
        agent_version: str | None = None,
        model_version: str | None = None,
        world_version: str | None = None,
        task_success: bool = False,
        resource_usage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Finalize an Arena run by building trajectory and computing metrics.

        This is the main integration point between C5 and C8.

        Pipeline (C8 §67):
          1. Load execution events from C1 EventRepository
          2. Build normalized trajectory via TrajectoryBuilder
          3. Persist trajectory via TrajectoryStore
          4. Compute metrics via MetricComputer
          5. Build performance profile via PerformanceProfileBuilder
          6. Save profile to database

        Returns:
            Dict with trajectory_id, profile_id, and summary.
        """
        logger.info(
            "arena_run_finalization_started",
            arena_run_id=arena_run_id,
            execution_id=execution_id,
        )

        # 1. Build trajectory from execution events
        trajectory_events, summary = await self._trajectory_builder.build_from_execution(
            execution_id=execution_id,
            arena_run_id=arena_run_id,
            configuration_hash=configuration_hash,
            agent_version=agent_version,
            model_version=model_version,
            world_version=world_version,
        )

        # 2. Persist trajectory
        trajectory_orm = await self._trajectory_store.save_trajectory(
            arena_run_id=arena_run_id,
            execution_id=execution_id,
            events=trajectory_events,
            summary=summary,
        )

        # 3. Compute performance profile
        metrics = self._metric_computer.to_metric_results()
        profile = self._profile_builder.compute_profile(
            arena_run_id=arena_run_id,
            metrics=metrics,
            trajectory_summary=summary,
            resource_usage=resource_usage or {},
            task_success=task_success,
        )

        # 4. Save profile
        profile_orm = await self._profile_builder.save_profile(profile)

        result = {
            "arena_run_id": arena_run_id,
            "trajectory_id": trajectory_orm.id,
            "profile_id": profile_orm.id,
            "event_count": summary.get("event_count", 0),
            "tool_calls": summary.get("tool_call_count", 0),
            "model_calls": summary.get("model_call_count", 0),
            "failures": summary.get("failure_count", 0),
            "duration_ms": summary.get("duration_ms", 0),
            "task_success": task_success,
            "dimensions": profile.dimensions,
        }

        logger.info(
            "arena_run_finalized",
            arena_run_id=arena_run_id,
            events=result["event_count"],
            task_success=task_success,
        )

        return result