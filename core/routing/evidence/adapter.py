# core/routing/evidence/adapter.py
"""
C9 Evidence Adapter — bridges C8 Arena results into C9 RoutingEvidence (§11).

Converts C8 MetricAggregation outputs and experiment run data into
the C9 RoutingEvidence contract.  Duck-types C8 objects so the
adapter stays loosely coupled to C8 internals (§55 Core Boundary).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.routing.contracts import RoutingEvidence
from core.routing.enums import EvidenceSourceType


class ArenaEvidenceAdapter:
    """Converts C8 Arena outputs into C9 RoutingEvidence.

    Accepts both C8 ``MetricAggregation`` dataclass instances *and*
    plain dicts with the same shape, keeping the C8→C9 boundary
    clean and testable without importing C8 ORM models.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def from_metric_aggregations(
        self,
        *,
        benchmark_id: str,
        benchmark_version: str,
        model_version: str,
        agent_version: str | None = None,
        world_version: str | None = None,
        aggregations: dict[str, Any],
        source_type: EvidenceSourceType = EvidenceSourceType.ARENA_BENCHMARK,
        observed_at: datetime | None = None,
    ) -> RoutingEvidence:
        """Convert a ``MetricComputer.compute()`` result dict.

        Args:
            benchmark_id: Arena benchmark identifier.
            benchmark_version: Version of the benchmark.
            model_version: Model version that was evaluated.
            agent_version: Agent version (if applicable).
            world_version: World version (if applicable).
            aggregations: ``{metric_id: MetricAggregation | dict}``
                as returned by ``MetricComputer.compute()``.
            source_type: Evidence origin tag.
            observed_at: When the observation was made.

        Returns:
            A single ``RoutingEvidence`` carrying all metrics.
        """
        if not benchmark_id:
            raise ValueError("benchmark_id must be non-empty")
        if not model_version:
            raise ValueError("model_version must be non-empty")

        metrics: dict[str, Any] = {}
        total_samples = 0

        for metric_id, agg in aggregations.items():
            mean = self._extract_mean(agg)
            if mean is not None:
                metrics[metric_id] = mean

            consensus = self._extract_consensus(agg)
            if consensus:
                metrics[f"{metric_id}_consensus"] = consensus

            samples = self._extract_sample_count(agg)
            total_samples = max(total_samples, samples)

        return RoutingEvidence(
            source_type=source_type,
            benchmark_id=benchmark_id,
            benchmark_version=benchmark_version,
            agent_version=agent_version,
            model_version=model_version,
            world_version=world_version,
            sample_count=total_samples,
            metrics=metrics,
            observed_at=observed_at or datetime.now(timezone.utc),
        )

    def from_experiment_runs(
        self,
        *,
        benchmark_id: str,
        benchmark_version: str,
        runs: list[dict[str, Any]],
        source_type: EvidenceSourceType = EvidenceSourceType.ARENA_EXPERIMENT,
        observed_at: datetime | None = None,
    ) -> list[RoutingEvidence]:
        """Convert completed Arena experiment runs into evidence.

        Each *completed* run with metrics produces one
        ``RoutingEvidence``.  Runs without metrics or with
        non-COMPLETED status are silently skipped.

        Args:
            benchmark_id: Arena benchmark identifier.
            benchmark_version: Benchmark version string.
            runs: List of run dicts, each with keys like
                ``model_version``, ``agent_version``,
                ``world_version``, ``status``, ``metrics``.
            source_type: Evidence origin tag.
            observed_at: Observation timestamp.

        Returns:
            List of ``RoutingEvidence``, one per usable run.
        """
        if not benchmark_id:
            raise ValueError("benchmark_id must be non-empty")

        evidence_list: list[RoutingEvidence] = []
        ts = observed_at or datetime.now(timezone.utc)

        for run in runs:
            status = str(run.get("status", "")).upper()
            if status != "COMPLETED":
                continue

            metrics = run.get("metrics")
            if not metrics or not isinstance(metrics, dict):
                continue

            model_version = run.get("model_version")
            if not model_version:
                continue

            evidence_list.append(
                RoutingEvidence(
                    source_type=source_type,
                    benchmark_id=benchmark_id,
                    benchmark_version=benchmark_version,
                    agent_version=run.get("agent_version"),
                    model_version=model_version,
                    world_version=run.get("world_version"),
                    sample_count=int(run.get("sample_count", 1)),
                    metrics=dict(metrics),
                    observed_at=ts,
                )
            )

        return evidence_list

    # ------------------------------------------------------------------
    # Duck-typing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_mean(agg: Any) -> float | None:
        """Pull mean value from MetricAggregation or dict."""
        if hasattr(agg, "mean_value"):
            return agg.mean_value
        if isinstance(agg, dict):
            if "mean_value" in agg:
                return agg["mean_value"]
            values = agg.get("values", [])
            if values:
                return sum(values) / len(values)
        return None

    @staticmethod
    def _extract_consensus(agg: Any) -> str | None:
        """Pull consensus string from MetricAggregation or dict."""
        if hasattr(agg, "consensus"):
            return agg.consensus
        if isinstance(agg, dict):
            return agg.get("consensus")
        return None

    @staticmethod
    def _extract_sample_count(agg: Any) -> int:
        """Pull sample count from MetricAggregation or dict."""
        if hasattr(agg, "sample_count"):
            return max(0, int(agg.sample_count))
        if isinstance(agg, dict):
            return max(0, int(agg.get("sample_count", 0)))
        return 0