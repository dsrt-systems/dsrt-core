"""
ArenaSDK Implementation (C8 §56).

Read-only access to Arena results. Evaluation remains external
to the agent (C8 §57).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.observability.logging import get_logger
from core.storage.models.arena import ArenaRunORM
from core.storage.models.arena_evaluation import PerformanceProfileORM
from sdk.agent.interfaces.arena import SDKArenaResult


logger = get_logger("sdk.arena")


class ArenaSDKImpl:
    """Read-only Arena SDK implementation (C8 §56).

    Agents can read past results but cannot modify evaluations.
    """

    def __init__(
        self,
        session: AsyncSession,
        agent_slug: str,
        agent_version: str,
    ) -> None:
        self._session = session
        self._agent_slug = agent_slug
        self._agent_version = agent_version

    async def get_last_result(
        self,
        benchmark_id: str | None = None,
    ) -> SDKArenaResult | None:
        """Get the most recent completed Arena result for this agent."""
        stmt = (
            select(ArenaRunORM)
            .where(
                ArenaRunORM.agent_slug == self._agent_slug,
                ArenaRunORM.status == "COMPLETED",
            )
        )
        if benchmark_id:
            stmt = stmt.where(ArenaRunORM.benchmark_id == benchmark_id)
        stmt = stmt.order_by(ArenaRunORM.completed_at.desc()).limit(1)

        result = await self._session.execute(stmt)
        run = result.scalar_one_or_none()

        if not run:
            return None

        # Load performance profile
        profile_stmt = select(PerformanceProfileORM).where(
            PerformanceProfileORM.arena_run_id == run.id,
        )
        profile_result = await self._session.execute(profile_stmt)
        profile = profile_result.scalar_one_or_none()

        dimensions = profile.dimensions if profile else {}
        task_success = profile.task_success if profile else False

        return SDKArenaResult(
            run_id=run.id,
            status=run.status,
            task_success=task_success,
            dimensions=dimensions,
        )

    async def get_capability_scores(self) -> dict[str, float]:
        """Get capability scores from past Arena runs."""
        # Load all completed runs for this agent
        stmt = (
            select(ArenaRunORM.id)
            .where(
                ArenaRunORM.agent_slug == self._agent_slug,
                ArenaRunORM.status == "COMPLETED",
            )
            .order_by(ArenaRunORM.completed_at.desc())
            .limit(20)
        )
        result = await self._session.execute(stmt)
        run_ids = [r[0] for r in result.all()]

        if not run_ids:
            return {}

        # Load profiles
        profile_stmt = select(PerformanceProfileORM).where(
            PerformanceProfileORM.arena_run_id.in_(run_ids),
        )
        profile_result = await self._session.execute(profile_stmt)
        profiles = list(profile_result.scalars().all())

        # Average dimensions across profiles
        dim_totals: dict[str, list[float]] = {}
        for p in profiles:
            for dim, val in (p.dimensions or {}).items():
                if dim not in dim_totals:
                    dim_totals[dim] = []
                dim_totals[dim].append(float(val))

        return {
            dim: round(sum(vals) / len(vals), 3)
            for dim, vals in dim_totals.items()
        }