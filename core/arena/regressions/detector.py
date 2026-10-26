"""
Regression Detector (C8 §38-42).

Compares performance across versions to detect material changes.

Supports:
  - Agent regression (v1.4 → v1.5)
  - Model regression (Model A v1 → Model A v2)
  - World regression (Research World v1 → v1.1)
  - Benchmark regression (any version change)

Key principle (C8 §38):
  Detect material changes, not noise. Use sample size and
  variance to distinguish real regressions from random fluctuation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.arena import RegressionResult
from schemas.domain.enums import MetricType, RegressionStatus

from core.observability.logging import get_logger
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.arena import ArenaRunORM
from core.storage.models.arena_evaluation import (
    PerformanceProfileORM,
    RegressionORM,
)


logger = get_logger("dsrt.arena.regressions")


@dataclass
class VersionComparison:
    """Side-by-side comparison of two versions."""
    metric_type: str
    baseline_mean: float | None = None
    candidate_mean: float | None = None
    delta: float | None = None
    delta_pct: float | None = None
    baseline_samples: int = 0
    candidate_samples: int = 0
    status: RegressionStatus = RegressionStatus.INCONCLUSIVE
    significant: bool = False


class RegressionDetector:
    """Detects performance regressions across versions (C8 §38-42).

    Usage:
        detector = RegressionDetector(session)
        results = await detector.detect_agent_regression(
            benchmark_id="research_v1",
            agent_slug="research_intelligence",
            baseline_version="1.0.0",
            candidate_version="1.1.0",
        )
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def detect_agent_regression(
        self,
        benchmark_id: str,
        agent_slug: str,
        baseline_version: str,
        candidate_version: str,
        min_samples: int = 3,
    ) -> list[RegressionResult]:
        """Compare agent versions on a benchmark (C8 §41)."""
        return await self._compare_versions(
            benchmark_id=benchmark_id,
            filter_field="agent_slug",
            filter_value=agent_slug,
            baseline_version=baseline_version,
            candidate_version=candidate_version,
            version_field="agent_version",
            min_samples=min_samples,
        )

    async def detect_model_regression(
        self,
        benchmark_id: str,
        model_slug: str,
        baseline_version: str,
        candidate_version: str,
        min_samples: int = 3,
    ) -> list[RegressionResult]:
        """Compare model versions on a benchmark (C8 §40)."""
        return await self._compare_versions(
            benchmark_id=benchmark_id,
            filter_field="model_slug",
            filter_value=model_slug,
            baseline_version=baseline_version,
            candidate_version=candidate_version,
            version_field="model_version",
            min_samples=min_samples,
        )

    async def detect_world_regression(
        self,
        benchmark_id: str,
        world_slug: str,
        baseline_version: str,
        candidate_version: str,
        min_samples: int = 3,
    ) -> list[RegressionResult]:
        """Compare world versions on a benchmark (C8 §42)."""
        return await self._compare_versions(
            benchmark_id=benchmark_id,
            filter_field="world_slug",
            filter_value=world_slug,
            baseline_version=baseline_version,
            candidate_version=candidate_version,
            version_field="world_version",
            min_samples=min_samples,
        )

    async def _compare_versions(
        self,
        benchmark_id: str,
        filter_field: str,
        filter_value: str,
        baseline_version: str,
        candidate_version: str,
        version_field: str,
        min_samples: int,
    ) -> list[RegressionResult]:
        """Generic version comparison engine."""
        # Load performance profiles for baseline
        baseline_profiles = await self._load_profiles(
            benchmark_id, filter_field, filter_value,
            version_field, baseline_version,
        )
        candidate_profiles = await self._load_profiles(
            benchmark_id, filter_field, filter_value,
            version_field, candidate_version,
        )

        if len(baseline_profiles) < min_samples or len(candidate_profiles) < min_samples:
            logger.warning(
                "insufficient_samples_for_regression",
                baseline=len(baseline_profiles),
                candidate=len(candidate_profiles),
                min_required=min_samples,
            )

        # Compare each dimension
        dimensions = [
            "correctness", "completeness", "reliability",
            "recovery", "tool_efficiency", "latency_ms",
            "estimated_cost_usd",
        ]

        results: list[RegressionResult] = []

        for dim in dimensions:
            baseline_vals = self._extract_dimension(baseline_profiles, dim)
            candidate_vals = self._extract_dimension(candidate_profiles, dim)

            comparison = self._compare_dimension(
                dim, baseline_vals, candidate_vals,
            )

            metric_type = self._dim_to_metric_type(dim)

            result = RegressionResult(
                id=new_id(IdPrefix.REGRESSION),
                benchmark_id=benchmark_id,
                metric_type=metric_type,
                baseline_version=baseline_version,
                candidate_version=candidate_version,
                baseline_value=comparison.baseline_mean,
                candidate_value=comparison.candidate_mean,
                delta=comparison.delta,
                status=comparison.status,
                sample_size=len(baseline_vals) + len(candidate_vals),
            )
            results.append(result)

        logger.info(
            "regression_detection_complete",
            benchmark=benchmark_id,
            baseline=baseline_version,
            candidate=candidate_version,
            dimensions_compared=len(results),
            regressions=sum(
                1 for r in results
                if r.status == RegressionStatus.REGRESSED
            ),
        )

        return results

    def _compare_dimension(
        self,
        dim: str,
        baseline: list[float],
        candidate: list[float],
    ) -> VersionComparison:
        """Compare a single dimension between two versions."""
        if not baseline or not candidate:
            return VersionComparison(metric_type=dim)

        b_mean = sum(baseline) / len(baseline)
        c_mean = sum(candidate) / len(candidate)
        delta = c_mean - b_mean

        # For latency and cost, lower is better (invert delta sign)
        if dim in ("latency_ms", "estimated_cost_usd"):
            delta_pct = (delta / b_mean * -100) if b_mean != 0 else 0
        else:
            delta_pct = (delta / b_mean * 100) if b_mean != 0 else 0

        # Determine significance (simple threshold: >5% change)
        significant = abs(delta_pct) > 5.0

        if not significant:
            status = RegressionStatus.UNCHANGED
        elif delta_pct > 0:
            status = RegressionStatus.IMPROVED
        else:
            status = RegressionStatus.REGRESSED

        return VersionComparison(
            metric_type=dim,
            baseline_mean=round(b_mean, 4),
            candidate_mean=round(c_mean, 4),
            delta=round(delta, 4),
            delta_pct=round(delta_pct, 2),
            baseline_samples=len(baseline),
            candidate_samples=len(candidate),
            status=status,
            significant=significant,
        )

    @staticmethod
    def _extract_dimension(
        profiles: list[PerformanceProfileORM], dim: str,
    ) -> list[float]:
        """Extract a dimension's values from profiles."""
        values = []
        for p in profiles:
            val = getattr(p, dim, None)
            if val is not None:
                values.append(float(val))
        return values

    @staticmethod
    def _dim_to_metric_type(dim: str) -> MetricType:
        """Map dimension name to MetricType enum."""
        mapping = {
            "correctness": MetricType.CORRECTNESS,
            "completeness": MetricType.COMPLETENESS,
            "reliability": MetricType.RELIABILITY,
            "recovery": MetricType.RECOVERY,
            "tool_efficiency": MetricType.TOOL_EFFICIENCY,
            "latency_ms": MetricType.LATENCY,
            "estimated_cost_usd": MetricType.COST,
        }
        return mapping.get(dim, MetricType.TASK_SUCCESS)

    async def _load_profiles(
        self,
        benchmark_id: str,
        filter_field: str,
        filter_value: str,
        version_field: str,
        version: str,
    ) -> list[PerformanceProfileORM]:
        """Load performance profiles matching the criteria."""
        # First find matching arena runs
        run_stmt = select(ArenaRunORM.id).where(
            ArenaRunORM.benchmark_id == benchmark_id,
            getattr(ArenaRunORM, filter_field) == filter_value,
            getattr(ArenaRunORM, version_field) == version,
            ArenaRunORM.status == "COMPLETED",
        )
        run_result = await self._session.execute(run_stmt)
        run_ids = [r[0] for r in run_result.all()]

        if not run_ids:
            return []

        # Load profiles for those runs
        profile_stmt = select(PerformanceProfileORM).where(
            PerformanceProfileORM.arena_run_id.in_(run_ids),
        )
        profile_result = await self._session.execute(profile_stmt)
        return list(profile_result.scalars().all())