"""
Performance Profile Builder (C8 §31-32, §64).

Assembles the final multi-dimensional PerformanceProfile from
aggregated metrics, trajectory data, and resource usage.

Key principles:
  - Dimensions are independent (C8 §31)
  - No single quality score (C8 §2)
  - Cost is separated by category (C8 §32)
  - Variance is preserved (C8 §36)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.arena import (
    ArenaRun,
    MetricResult,
    PerformanceProfile,
)
from schemas.domain.enums import MetricType

from core.observability.logging import get_logger
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.arena_evaluation import (
    MetricResultORM,
    PerformanceProfileORM,
)


logger = get_logger("dsrt.arena.profiles")


class PerformanceProfileBuilder:
    """Builds multi-dimensional performance profiles (C8 §31-32, §64).

    Usage:
        builder = PerformanceProfileBuilder(session)
        profile = await builder.build_profile(
            arena_run_id="arn_1",
            metrics=metric_results,
            trajectory_summary={"duration_ms": 184000, ...},
            resource_usage={"model_cost": 0.50, "tool_cost": 0.11, ...},
        )
    """

    def __init__(self, session: AsyncSession | None = None) -> None:
        self._session = session

    def compute_profile(
        self,
        *,
        arena_run_id: str,
        metrics: list[MetricResult],
        trajectory_summary: dict[str, Any] | None = None,
        resource_usage: dict[str, Any] | None = None,
        task_success: bool = False,
    ) -> PerformanceProfile:
        """Compute a performance profile from metrics and metadata.

        This is a pure computation — no database access required.

        Args:
            arena_run_id: The Arena run this profile belongs to.
            metrics: Aggregated MetricResult list from MetricComputer.
            trajectory_summary: Summary from TrajectoryBuilder.
            resource_usage: Resource usage breakdown.
            task_success: Whether the overall task succeeded.

        Returns:
            PerformanceProfile with all dimensions populated.
        """
        traj = trajectory_summary or {}
        resources = resource_usage or {}

        # Extract dimension values from metrics
        dims = self._extract_dimensions(metrics)

        # Cost separation (C8 §32)
        model_cost = float(resources.get("model_cost_usd", 0))
        tool_cost = float(resources.get("tool_cost_usd", 0))
        world_cost = float(resources.get("world_cost_usd", 0))
        total_cost = float(resources.get("estimated_cost_usd", 0))
        if total_cost == 0:
            total_cost = model_cost + tool_cost + world_cost

        now = datetime.now(timezone.utc)

        profile = PerformanceProfile(
            id=new_id(IdPrefix.PERFORMANCE_PROFILE),
            arena_run_id=arena_run_id,
            task_success=task_success,
            correctness=dims.get("correctness"),
            completeness=dims.get("completeness"),
            evidence_quality=dims.get("evidence_quality"),
            reliability=dims.get("reliability"),
            recovery=dims.get("recovery"),
            tool_efficiency=dims.get("tool_efficiency"),
            constraint_adherence=dims.get("constraint_adherence"),
            safety=dims.get("safety"),
            latency_ms=int(traj.get("duration_ms", 0)),
            estimated_cost_usd=total_cost,
            model_cost_usd=model_cost,
            tool_cost_usd=tool_cost,
            world_cost_usd=world_cost,
            human_intervention_count=int(resources.get("human_interventions", 0)),
            model_call_count=int(traj.get("model_call_count", 0)),
            tool_call_count=int(traj.get("tool_call_count", 0)),
            failure_count=int(traj.get("failure_count", 0)),
            recovery_count=int(traj.get("recovery_count", 0)),
            metrics=metrics,
            dimensions=dims,
            created_at=now,
            updated_at=now,
        )

        logger.info(
            "performance_profile_computed",
            arena_run_id=arena_run_id,
            task_success=task_success,
            dimensions=len(dims),
            latency_ms=profile.latency_ms,
            cost=total_cost,
        )

        return profile

    async def save_profile(
        self,
        profile: PerformanceProfile,
    ) -> PerformanceProfileORM:
        """Persist a performance profile and its metrics to the database.

        Args:
            profile: The computed PerformanceProfile.

        Returns:
            The persisted PerformanceProfileORM.
        """
        if not self._session:
            raise RuntimeError("Database session required for save_profile.")

        # Save the profile
        orm = PerformanceProfileORM(
            id=profile.id,
            arena_run_id=profile.arena_run_id,
            task_success=profile.task_success,
            correctness=profile.correctness,
            completeness=profile.completeness,
            evidence_quality=profile.evidence_quality,
            reliability=profile.reliability,
            recovery=profile.recovery,
            tool_efficiency=profile.tool_efficiency,
            constraint_adherence=profile.constraint_adherence,
            safety=profile.safety,
            latency_ms=profile.latency_ms,
            estimated_cost_usd=profile.estimated_cost_usd,
            model_cost_usd=profile.model_cost_usd,
            tool_cost_usd=profile.tool_cost_usd,
            world_cost_usd=profile.world_cost_usd,
            human_intervention_count=profile.human_intervention_count,
            model_call_count=profile.model_call_count,
            tool_call_count=profile.tool_call_count,
            failure_count=profile.failure_count,
            recovery_count=profile.recovery_count,
            dimensions=profile.dimensions,
        )
        self._session.add(orm)

        # Save individual metrics
        for m in profile.metrics:
            metric_orm = MetricResultORM(
                id=new_id(IdPrefix.METRIC_RESULT),
                arena_run_id=profile.arena_run_id,
                metric_id=m.metric_id,
                metric_type=(
                    m.metric_type.value
                    if hasattr(m.metric_type, "value")
                    else str(m.metric_type)
                ),
                metric_version=m.metric_version,
                value_numeric=m.value_numeric,
                value_boolean=m.value_boolean,
                value_text=m.value_text,
                evaluator_type=(
                    m.evaluator_type.value
                    if hasattr(m.evaluator_type, "value")
                    else str(m.evaluator_type)
                ),
                sample_count=m.sample_count,
                confidence=m.confidence,
                evidence_refs=m.evidence_refs,
                explanation=m.explanation,
            )
            self._session.add(metric_orm)

        await self._session.flush()

        logger.info(
            "performance_profile_saved",
            profile_id=profile.id,
            arena_run_id=profile.arena_run_id,
            metrics_count=len(profile.metrics),
        )

        return orm

    @staticmethod
    def _extract_dimensions(
        metrics: list[MetricResult],
    ) -> dict[str, float]:
        """Extract named dimensions from metric results.

        Maps MetricType values to dimension names used in
        PerformanceProfile (C8 §31).
        """
        dims: dict[str, float] = {}

        type_to_dim = {
            MetricType.CORRECTNESS.value: "correctness",
            MetricType.COMPLETENESS.value: "completeness",
            MetricType.EVIDENCE_QUALITY.value: "evidence_quality",
            MetricType.RELIABILITY.value: "reliability",
            MetricType.RECOVERY.value: "recovery",
            MetricType.TOOL_EFFICIENCY.value: "tool_efficiency",
            MetricType.CONSTRAINT_ADHERENCE.value: "constraint_adherence",
            MetricType.SAFETY.value: "safety",
        }

        for m in metrics:
            mt = (
                m.metric_type.value
                if hasattr(m.metric_type, "value")
                else str(m.metric_type)
            )
            dim_name = type_to_dim.get(mt)
            if dim_name and m.value_numeric is not None:
                # If multiple metrics map to the same dimension, average them
                if dim_name in dims:
                    dims[dim_name] = (dims[dim_name] + m.value_numeric) / 2
                else:
                    dims[dim_name] = m.value_numeric

        return dims

    @staticmethod
    def profile_summary(profile: PerformanceProfile) -> dict[str, Any]:
        """Generate a human-readable summary of a performance profile.

        This is for display purposes — the underlying dimensions
        remain separate and are never collapsed to one score.
        """
        lines = []
        lines.append(f"Task Success: {'YES' if profile.task_success else 'NO'}")

        for dim in [
            "correctness", "completeness", "evidence_quality",
            "reliability", "recovery", "tool_efficiency",
            "constraint_adherence", "safety",
        ]:
            val = getattr(profile, dim, None)
            if val is not None:
                lines.append(f"  {dim.replace('_', ' ').title()}: {val:.2f}")

        lines.append(f"  Latency: {profile.latency_ms}ms")
        lines.append(f"  Cost: ${profile.estimated_cost_usd:.4f}")
        lines.append(f"    Model: ${profile.model_cost_usd:.4f}")
        lines.append(f"    Tool: ${profile.tool_cost_usd:.4f}")
        lines.append(f"    World: ${profile.world_cost_usd:.4f}")
        lines.append(f"  Model calls: {profile.model_call_count}")
        lines.append(f"  Tool calls: {profile.tool_call_count}")
        lines.append(f"  Failures: {profile.failure_count}")
        lines.append(f"  Recoveries: {profile.recovery_count}")
        lines.append(f"  Human interventions: {profile.human_intervention_count}")

        return {
            "text": "\n".join(lines),
            "task_success": profile.task_success,
            "dimensions": profile.dimensions,
            "cost_breakdown": {
                "model": profile.model_cost_usd,
                "tool": profile.tool_cost_usd,
                "world": profile.world_cost_usd,
                "total": profile.estimated_cost_usd,
            },
        }