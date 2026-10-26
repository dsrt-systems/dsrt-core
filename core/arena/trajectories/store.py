"""
Trajectory Store (C8 §16-19, §44, §54).

Persists and queries Arena trajectories. Trajectories are immutable
once finalized — they represent the historical record of what happened.

Key principles:
  - Trajectories are append-only during execution
  - Once finalized, trajectories are immutable (C8 §73)
  - Configuration hash enables reproducibility (C8 §54)
  - Trajectory data references sensitive content, never embeds it (C8 §19)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.arena import Trajectory, TrajectoryEvent
from schemas.domain.enums import EventType

from core.observability.logging import get_logger
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.arena_evaluation import (
    TrajectoryEventORM,
    TrajectoryORM,
)


logger = get_logger("dsrt.arena.trajectory.store")


class TrajectoryStore:
    """Persists and queries Arena trajectories (C8 §16-19).

    Usage:
        store = TrajectoryStore(session)
        trajectory = await store.save_trajectory(
            arena_run_id="arn_1",
            execution_id="exe_1",
            events=trajectory_events,
            summary=summary_dict,
        )
        loaded = await store.get_trajectory("arn_1")
        events = await store.get_trajectory_events(trajectory.id)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_trajectory(
        self,
        *,
        arena_run_id: str,
        execution_id: str,
        events: list[TrajectoryEvent],
        summary: dict[str, Any],
    ) -> TrajectoryORM:
        """Save a complete trajectory with all events (C8 §16).

        This is typically called once after an Arena run completes.
        The trajectory is immutable after saving.

        Args:
            arena_run_id: The Arena run this trajectory belongs to.
            execution_id: The C1 execution ID.
            events: Normalized TrajectoryEvent list from TrajectoryBuilder.
            summary: Summary dict from TrajectoryBuilder.build().

        Returns:
            The persisted TrajectoryORM.
        """
        # Check if trajectory already exists (idempotent)
        existing = await self.get_trajectory_by_run(arena_run_id)
        if existing:
            logger.warning(
                "trajectory_already_exists",
                arena_run_id=arena_run_id,
                trajectory_id=existing.id,
            )
            return existing

        # Create trajectory record
        trajectory = TrajectoryORM(
            id=new_id(IdPrefix.TRAJECTORY),
            arena_run_id=arena_run_id,
            execution_id=execution_id,
            event_count=summary.get("event_count", len(events)),
            start_state_hash=summary.get("start_state_hash", ""),
            final_state_hash=summary.get("final_state_hash", ""),
            artifact_count=summary.get("artifact_count", 0),
            tool_call_count=summary.get("tool_call_count", 0),
            model_call_count=summary.get("model_call_count", 0),
            duration_ms=summary.get("duration_ms", 0),
            configuration_hash=summary.get("configuration_hash", ""),
        )
        self._session.add(trajectory)
        await self._session.flush()

        # Persist individual events
        for te in events:
            event_orm = TrajectoryEventORM(
                id=new_id(IdPrefix.TRAJECTORY),
                trajectory_id=trajectory.id,
                sequence=te.sequence,
                timestamp=te.timestamp,
                event_type=te.event_type,
                source=te.source,
                agent_version=te.agent_version,
                model_version=te.model_version,
                world_version=te.world_version,
                node_id=te.node_id,
                tool_slug=te.tool_slug,
                target=te.target,
                latency_ms=te.latency_ms,
                tokens=te.tokens,
                cost_usd=te.cost_usd,
                error=te.error,
                payload=te.payload,
            )
            self._session.add(event_orm)

        await self._session.flush()

        logger.info(
            "trajectory_saved",
            trajectory_id=trajectory.id,
            arena_run_id=arena_run_id,
            event_count=len(events),
            duration_ms=trajectory.duration_ms,
        )

        return trajectory

    async def get_trajectory_by_run(
        self, arena_run_id: str,
    ) -> TrajectoryORM | None:
        """Get the trajectory for an Arena run."""
        stmt = select(TrajectoryORM).where(
            TrajectoryORM.arena_run_id == arena_run_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_trajectory(
        self, trajectory_id: str,
    ) -> TrajectoryORM | None:
        """Get a trajectory by ID."""
        stmt = select(TrajectoryORM).where(
            TrajectoryORM.id == trajectory_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_trajectory_events(
        self,
        trajectory_id: str,
        event_type: str | None = None,
        limit: int = 1000,
    ) -> list[TrajectoryEventORM]:
        """Get events for a trajectory, optionally filtered by type."""
        stmt = (
            select(TrajectoryEventORM)
            .where(TrajectoryEventORM.trajectory_id == trajectory_id)
        )
        if event_type:
            stmt = stmt.where(TrajectoryEventORM.event_type == event_type)
        stmt = stmt.order_by(
            TrajectoryEventORM.sequence.asc(),
        ).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_trajectory_summary(
        self, arena_run_id: str,
    ) -> dict[str, Any] | None:
        """Get a summary of the trajectory for an Arena run."""
        trajectory = await self.get_trajectory_by_run(arena_run_id)
        if not trajectory:
            return None

        return {
            "trajectory_id": trajectory.id,
            "arena_run_id": arena_run_id,
            "execution_id": trajectory.execution_id,
            "event_count": trajectory.event_count,
            "tool_call_count": trajectory.tool_call_count,
            "model_call_count": trajectory.model_call_count,
            "artifact_count": trajectory.artifact_count,
            "duration_ms": trajectory.duration_ms,
            "start_state_hash": trajectory.start_state_hash,
            "final_state_hash": trajectory.final_state_hash,
            "configuration_hash": trajectory.configuration_hash,
        }

    async def compare_trajectories(
        self,
        run_id_a: str,
        run_id_b: str,
    ) -> dict[str, Any]:
        """Compare two trajectories for regression analysis (C8 §38).

        Returns a side-by-side comparison of key metrics.
        """
        traj_a = await self.get_trajectory_by_run(run_id_a)
        traj_b = await self.get_trajectory_by_run(run_id_b)

        if not traj_a or not traj_b:
            return {
                "error": "One or both trajectories not found.",
                "run_a": run_id_a,
                "run_b": run_id_b,
            }

        return {
            "run_a": {
                "arena_run_id": run_id_a,
                "event_count": traj_a.event_count,
                "tool_calls": traj_a.tool_call_count,
                "model_calls": traj_a.model_call_count,
                "duration_ms": traj_a.duration_ms,
                "config_hash": traj_a.configuration_hash,
            },
            "run_b": {
                "arena_run_id": run_id_b,
                "event_count": traj_b.event_count,
                "tool_calls": traj_b.tool_call_count,
                "model_calls": traj_b.model_call_count,
                "duration_ms": traj_b.duration_ms,
                "config_hash": traj_b.configuration_hash,
            },
            "deltas": {
                "event_count": traj_b.event_count - traj_a.event_count,
                "tool_calls": traj_b.tool_call_count - traj_a.tool_call_count,
                "model_calls": traj_b.model_call_count - traj_a.model_call_count,
                "duration_ms": traj_b.duration_ms - traj_a.duration_ms,
            },
            "same_configuration": (
                traj_a.configuration_hash == traj_b.configuration_hash
            ),
        }

    async def get_failure_events(
        self,
        trajectory_id: str,
    ) -> list[TrajectoryEventORM]:
        """Get all failure events from a trajectory (C8 §45-46)."""
        failure_types = [
            EventType.EXECUTION_FAILED.value,
            EventType.AGENT_EXECUTION_FAILED.value,
            EventType.MODEL_REQUEST_FAILED.value,
            EventType.TOOL_CALL_FAILED.value,
            EventType.TOOL_FAILED.value,
            EventType.NODE_FAILED.value,
            EventType.VERIFICATION_FAILED.value,
            EventType.WORLD_FAILURE.value,
        ]
        stmt = (
            select(TrajectoryEventORM)
            .where(
                TrajectoryEventORM.trajectory_id == trajectory_id,
                TrajectoryEventORM.event_type.in_(failure_types),
            )
            .order_by(TrajectoryEventORM.sequence.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())