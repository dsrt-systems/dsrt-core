"""C9.10 - Arena Evidence Bridge.

Bridges C8 Arena run data to C9 RoutingEvidence contracts.
Uses dict-based interface to avoid hard coupling to C8 internals.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.routing.contracts import RoutingEvidence
from core.routing.enums import EvidenceSourceType


_USABLE_STATUSES = frozenset({"COMPLETED"})

_METRIC_ALIASES: dict[str, str] = {
    "task_success": "quality_score",
    "accuracy": "quality_score",
    "f1_score": "quality_score",
    "latency_ms": "latency_ms",
    "p50_latency_ms": "latency_ms",
    "cost_usd": "cost_usd",
    "total_cost": "cost_usd",
    "reliability": "reliability_score",
    "success_rate": "reliability_score",
    "total_tokens": "token_usage",
    "token_count": "token_usage",
}


class ArenaEvidenceBridge:
    """Transforms C8 Arena data into C9 routing evidence."""

    def __init__(self, max_evidence_age_hours: int = 168) -> None:
        self._max_age_hours = max_evidence_age_hours

    def transform_run_to_evidence(
        self,
        run_data: dict[str, Any],
        metrics: dict[str, Any] | None = None,
    ) -> RoutingEvidence | None:
        if not self._is_run_usable(run_data):
            return None

        metrics = metrics or run_data.get("metrics") or {}

        quality = self._extract_metric(metrics, "quality_score", 0.0)
        latency = self._extract_metric(metrics, "latency_ms", 0.0)
        cost = self._extract_metric(metrics, "cost_usd", 0.0)
        reliability = self._extract_metric(metrics, "reliability_score", 0.0)
        tokens = self._extract_metric(metrics, "token_usage", 0.0)

        ts = run_data.get("completed_at") or run_data.get("created_at")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                ts = datetime.now(timezone.utc)
        elif ts is None:
            ts = datetime.now(timezone.utc)

        source_type = self._infer_source_type(run_data)

        return RoutingEvidence(
            source_type=source_type,
            benchmark_id=run_data.get("benchmark_id"),
            benchmark_version=run_data.get("benchmark_version"),
            agent_version=run_data.get("agent_version") or run_data.get("agent_slug"),
            model_version=run_data.get("model_version") or run_data.get("model_slug"),
            world_version=run_data.get("world_version") or run_data.get("world_slug"),
            sample_count=1,
            metrics={
                "quality_score": quality,
                "latency_ms": latency,
                "cost_usd": cost,
                "reliability_score": reliability,
                "token_usage": tokens,
                "agent_slug": run_data.get("agent_slug", ""),
                "model_slug": run_data.get("model_slug", ""),
                "provider_id": run_data.get("provider_id", ""),
                "configuration_hash": run_data.get("configuration_hash", ""),
                "repetition": run_data.get("repetition", 1),
            },
            observed_at=ts,
        )

    def transform_runs_batch(
        self, runs: list[dict[str, Any]],
    ) -> list[RoutingEvidence]:
        results: list[RoutingEvidence] = []
        for run in runs:
            ev = self.transform_run_to_evidence(run)
            if ev is not None:
                results.append(ev)
        return results

    def _is_run_usable(self, run_data: dict[str, Any]) -> bool:
        status = run_data.get("status", "")
        if status not in _USABLE_STATUSES:
            return False
        if not run_data.get("agent_slug") and not run_data.get("model_slug"):
            return False
        return True

    def _extract_metric(
        self, metrics: dict[str, Any], c9_key: str, default: float = 0.0,
    ) -> float:
        if c9_key in metrics:
            return self._to_float(metrics[c9_key], default)
        for arena_key, mapped in _METRIC_ALIASES.items():
            if mapped == c9_key and arena_key in metrics:
                return self._to_float(metrics[arena_key], default)
        return default

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _infer_source_type(run_data: dict[str, Any]) -> EvidenceSourceType:
        if run_data.get("benchmark_id"):
            return EvidenceSourceType.ARENA_BENCHMARK
        if run_data.get("experiment_id"):
            return EvidenceSourceType.ARENA_EXPERIMENT
        return EvidenceSourceType.ARENA_BENCHMARK
