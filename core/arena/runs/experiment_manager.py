"""
Experiment Manager (C8 §5, §33-37).

Creates and manages experiments — configuration matrices that define
which Agent × Model × World × Task combinations to evaluate.

Key principles:
  - Benchmark ≠ Experiment ≠ Run (C8 §5)
  - Configurations are explicit (C8 §34)
  - Repeated runs for nondeterminism (C8 §35)
  - Variance is preserved, not hidden (C8 §36)
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.arena import Experiment, ExperimentConfiguration
from schemas.domain.enums import ArenaRunStatus

from core.api.errors.exceptions import ConflictError, NotFoundError
from core.observability.logging import get_logger
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.arena import ArenaRunORM, ExperimentORM


logger = get_logger("dsrt.arena.experiments")


class ExperimentManager:
    """Manages Arena experiments and their configuration matrices (C8 §33-34).

    Usage:
        mgr = ExperimentManager(session)
        experiment = await mgr.create_experiment(
            benchmark_id="research_v1",
            benchmark_version="1.0.0",
            name="GPT vs Gemini Research Comparison",
            configurations=[
                {"agent_slug": "research_intelligence", "agent_version": "1.0.0",
                 "model_slug": "gpt-4o", "task_definition_id": "R001"},
                {"agent_slug": "research_intelligence", "agent_version": "1.0.0",
                 "model_slug": "gemini-pro", "task_definition_id": "R001"},
            ],
            repetitions=3,
        )
        runs = await mgr.expand_runs(experiment.id)
        # Creates 2 configs × 3 repetitions = 6 ArenaRunORM records
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_experiment(
        self,
        *,
        benchmark_id: str,
        benchmark_version: str,
        name: str = "",
        description: str = "",
        configurations: list[dict[str, Any]],
        repetitions: int = 1,
        organization_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExperimentORM:
        """Create a new experiment with a configuration matrix (C8 §33-34).

        Args:
            benchmark_id: The benchmark being evaluated.
            benchmark_version: Version of the benchmark.
            name: Human-readable experiment name.
            configurations: List of config dicts, each with:
                agent_slug, agent_version, model_slug, model_version,
                world_slug, world_version, task_definition_id, task_version
            repetitions: Number of times to repeat each configuration (C8 §35).
            organization_id: Owning organization.

        Returns:
            The persisted ExperimentORM.
        """
        if not configurations:
            raise ValueError("Experiment must have at least one configuration.")
        if repetitions < 1:
            raise ValueError("Repetitions must be >= 1.")

        experiment = ExperimentORM(
            id=new_id(IdPrefix.EXPERIMENT),
            benchmark_id=benchmark_id,
            benchmark_version=benchmark_version,
            name=name,
            description=description,
            configurations=configurations,
            repetitions=repetitions,
            organization_id=organization_id,
            status="CREATED",
            metadata_json=metadata or {},
        )
        self._session.add(experiment)
        await self._session.flush()

        logger.info(
            "experiment_created",
            experiment_id=experiment.id,
            benchmark=benchmark_id,
            configurations=len(configurations),
            repetitions=repetitions,
            total_runs=len(configurations) * repetitions,
        )

        return experiment

    async def expand_runs(
        self,
        experiment_id: str,
    ) -> list[ArenaRunORM]:
        """Expand an experiment into individual ArenaRun records (C8 §34-35).

        Creates one ArenaRun per configuration × repetition.
        Each run gets a unique configuration hash for reproducibility (C8 §43).

        Returns:
            List of created ArenaRunORM records.
        """
        experiment = await self.get_experiment(experiment_id)
        if not experiment:
            raise NotFoundError(f"Experiment '{experiment_id}' not found.")

        runs: list[ArenaRunORM] = []

        for config_idx, config in enumerate(experiment.configurations):
            agent_slug = config.get("agent_slug", "unknown")
            agent_version = config.get("agent_version", "1.0.0")
            model_slug = config.get("model_slug")
            model_version = config.get("model_version")
            world_slug = config.get("world_slug")
            world_version = config.get("world_version")
            task_definition_id = config.get("task_definition_id", "")
            task_version = config.get("task_version", "1.0")

            for rep in range(1, experiment.repetitions + 1):
                # Build configuration hash (C8 §43)
                config_hash = self._compute_config_hash(
                    agent_slug=agent_slug,
                    agent_version=agent_version,
                    model_slug=model_slug,
                    model_version=model_version,
                    world_slug=world_slug,
                    world_version=world_version,
                    task_definition_id=task_definition_id,
                    task_version=task_version,
                    benchmark_id=experiment.benchmark_id,
                    benchmark_version=experiment.benchmark_version,
                    repetition=rep,
                )

                run = ArenaRunORM(
                    id=new_id(IdPrefix.ARENA_RUN),
                    benchmark_id=experiment.benchmark_id,
                    benchmark_version=experiment.benchmark_version,
                    experiment_id=experiment.id,
                    task_definition_id=task_definition_id,
                    agent_slug=agent_slug,
                    agent_version=agent_version,
                    model_slug=model_slug,
                    model_version=model_version,
                    world_slug=world_slug,
                    world_version=world_version,
                    configuration_hash=config_hash,
                    status=ArenaRunStatus.CREATED.value,
                    repetition=rep,
                    seed=rep,  # Default seed = repetition number
                )
                self._session.add(run)
                runs.append(run)

        await self._session.flush()

        # Update experiment status
        experiment.status = "EXPANDED"
        await self._session.flush()

        logger.info(
            "experiment_expanded",
            experiment_id=experiment_id,
            total_runs=len(runs),
        )

        return runs

    async def get_experiment(
        self, experiment_id: str,
    ) -> ExperimentORM | None:
        """Get an experiment by ID."""
        stmt = select(ExperimentORM).where(
            ExperimentORM.id == experiment_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_experiments(
        self,
        benchmark_id: str | None = None,
        organization_id: str | None = None,
        limit: int = 50,
    ) -> list[ExperimentORM]:
        """List experiments with optional filters."""
        stmt = select(ExperimentORM).order_by(
            ExperimentORM.created_at.desc(),
        )
        if benchmark_id:
            stmt = stmt.where(ExperimentORM.benchmark_id == benchmark_id)
        if organization_id:
            stmt = stmt.where(ExperimentORM.organization_id == organization_id)
        stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_experiment_runs(
        self, experiment_id: str,
    ) -> list[ArenaRunORM]:
        """Get all runs for an experiment."""
        stmt = (
            select(ArenaRunORM)
            .where(ArenaRunORM.experiment_id == experiment_id)
            .order_by(ArenaRunORM.repetition.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_experiment_summary(
        self, experiment_id: str,
    ) -> dict[str, Any]:
        """Get a summary of experiment run statuses (C8 §36).

        Does NOT collapse to a single score. Preserves the distribution.
        """
        runs = await self.get_experiment_runs(experiment_id)

        status_counts: dict[str, int] = {}
        for run in runs:
            s = run.status
            status_counts[s] = status_counts.get(s, 0) + 1

        return {
            "experiment_id": experiment_id,
            "total_runs": len(runs),
            "status_distribution": status_counts,
            "completed": status_counts.get(ArenaRunStatus.COMPLETED.value, 0),
            "failed": status_counts.get(ArenaRunStatus.FAILED.value, 0),
            "running": status_counts.get(ArenaRunStatus.RUNNING.value, 0),
            "pending": sum(
                v for k, v in status_counts.items()
                if k in (
                    ArenaRunStatus.CREATED.value,
                    ArenaRunStatus.QUEUED.value,
                )
            ),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_config_hash(
        **kwargs: Any,
    ) -> str:
        """Compute a deterministic configuration hash (C8 §43).

        Includes: agent, model, world, task, benchmark versions + repetition.
        """
        from core.kernel.fingerprint import content_hash

        canonical = {k: v for k, v in sorted(kwargs.items()) if v is not None}
        return content_hash(str(canonical))