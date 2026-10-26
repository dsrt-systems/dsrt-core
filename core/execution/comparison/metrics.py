# Path: core/execution/comparison/metrics.py
"""
Dimension-level metric calculations for multi-configuration comparisons.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.execution.comparison.contracts import (
    ConfigurationRunEvidence,
    DimensionComparison,
)


class ComparisonMetricsCalculator:
    """Pure functions for ranking and delta computation per dimension."""

    @staticmethod
    def _rank_by(
        runs: Sequence[ConfigurationRunEvidence],
        key_fn,
        *,
        higher_is_better: bool,
        skip_none: bool = True,
    ) -> Tuple[List[str], Optional[str], Dict[str, Any]]:
        scored: List[Tuple[str, float]] = []
        values: Dict[str, Any] = {}
        for r in runs:
            val = key_fn(r)
            values[r.configuration_id] = val
            if val is None and skip_none:
                continue
            if val is None:
                continue
            scored.append((r.configuration_id, float(val)))

        reverse = higher_is_better
        scored.sort(key=lambda x: x[1], reverse=reverse)
        ranking = [cid for cid, _ in scored]
        best = ranking[0] if ranking else None
        return ranking, best, values

    def quality(self, runs: Sequence[ConfigurationRunEvidence]) -> DimensionComparison:
        ranking, best, values = self._rank_by(
            runs, lambda r: r.overall_score, higher_is_better=True
        )
        notes: List[str] = []
        missing = [r.configuration_id for r in runs if r.overall_score is None]
        if missing:
            notes.append(
                f"overall_score unavailable for: {', '.join(missing)} "
                "(qualitative-only or failed evaluation)."
            )
        comparable = len(missing) == 0 and len(runs) >= 2
        delta: Dict[str, Any] = {}
        if best is not None:
            base = values.get(best)
            for cid, val in values.items():
                if cid == best or val is None or base is None:
                    continue
                delta[cid] = round(float(base) - float(val), 6)
        return DimensionComparison(
            dimension="quality",
            values=values,
            ranking=ranking,
            best_configuration_id=best,
            delta=delta,
            comparable=comparable,
            notes=notes,
        )

    def completion(self, runs: Sequence[ConfigurationRunEvidence]) -> DimensionComparison:
        values: Dict[str, Any] = {}
        ranking_scores: List[Tuple[str, float]] = []
        for r in runs:
            if r.task_success is True or r.succeeded:
                score = 1.0
            elif r.failed or r.cancelled:
                score = 0.0
            elif r.task_success is False:
                score = 0.0
            else:
                score = 0.5 if r.run_status.upper() in {"PARTIALLY_COMPLETED", "PARTIAL"} else None
            values[r.configuration_id] = {
                "task_success": r.task_success,
                "succeeded": r.succeeded,
                "run_status": r.run_status,
                "completion_score": score,
            }
            if score is not None:
                ranking_scores.append((r.configuration_id, score))
        ranking_scores.sort(key=lambda x: x[1], reverse=True)
        ranking = [c for c, _ in ranking_scores]
        return DimensionComparison(
            dimension="completion",
            values=values,
            ranking=ranking,
            best_configuration_id=ranking[0] if ranking else None,
            comparable=all(
                isinstance(values[c].get("completion_score"), (int, float))
                for c in values
            ),
        )

    def correctness(self, runs: Sequence[ConfigurationRunEvidence]) -> DimensionComparison:
        ranking, best, values = self._rank_by(
            runs, lambda r: r.correctness_score, higher_is_better=True
        )
        return DimensionComparison(
            dimension="correctness",
            values=values,
            ranking=ranking,
            best_configuration_id=best,
            comparable=all(v is not None for v in values.values()) and len(runs) >= 2,
        )

    def reliability(self, runs: Sequence[ConfigurationRunEvidence]) -> DimensionComparison:
        values: Dict[str, Any] = {}
        scored: List[Tuple[str, float]] = []
        for r in runs:
            # Prefer explicit reliability_score; else derive from failure signals
            if r.reliability_score is not None:
                rel = float(r.reliability_score)
            else:
                if r.failed:
                    rel = 0.0
                elif r.succeeded and r.error_count == 0:
                    rel = 1.0
                elif r.succeeded:
                    rel = max(0.0, 1.0 - 0.1 * r.error_count)
                else:
                    rel = 0.3 if r.run_status.upper() == "PARTIALLY_COMPLETED" else 0.0
            values[r.configuration_id] = {
                "reliability_score": rel,
                "error_count": r.error_count,
                "repair_count": r.repair_count,
                "failed": r.failed,
            }
            scored.append((r.configuration_id, rel))
        scored.sort(key=lambda x: x[1], reverse=True)
        ranking = [c for c, _ in scored]
        return DimensionComparison(
            dimension="reliability",
            values=values,
            ranking=ranking,
            best_configuration_id=ranking[0] if ranking else None,
            comparable=True,
        )

    def cost(self, runs: Sequence[ConfigurationRunEvidence]) -> DimensionComparison:
        ranking, best, raw_values = self._rank_by(
            runs, lambda r: r.total_cost_usd, higher_is_better=False
        )
        values: Dict[str, Any] = {}
        notes: List[str] = []
        for r in runs:
            values[r.configuration_id] = {
                "total_cost_usd": r.total_cost_usd,
                "availability": r.cost_availability,
                "model_cost_usd": r.model_cost_usd,
                "tool_cost_usd": r.tool_cost_usd,
                "verification_cost_usd": r.verification_cost_usd,
                "recovery_cost_usd": r.recovery_cost_usd,
            }
            if r.cost_availability == "UNAVAILABLE" or r.total_cost_usd is None:
                notes.append(f"cost unavailable for {r.configuration_id}")
            elif r.cost_availability == "ESTIMATED":
                notes.append(f"cost estimated for {r.configuration_id}")
        comparable = all(
            r.total_cost_usd is not None and r.cost_availability != "UNAVAILABLE"
            for r in runs
        )
        delta: Dict[str, Any] = {}
        if best is not None:
            base = raw_values.get(best)
            for cid, val in raw_values.items():
                if cid == best or val is None or base is None:
                    continue
                delta[cid] = round(float(val) - float(base), 6)
        return DimensionComparison(
            dimension="cost",
            values=values,
            ranking=ranking,
            best_configuration_id=best,
            delta=delta,
            comparable=comparable,
            notes=notes,
        )

    def latency(self, runs: Sequence[ConfigurationRunEvidence]) -> DimensionComparison:
        ranking, best, values = self._rank_by(
            runs, lambda r: r.latency_ms, higher_is_better=False
        )
        return DimensionComparison(
            dimension="latency",
            values=values,
            ranking=ranking,
            best_configuration_id=best,
            comparable=all(v is not None for v in values.values()) and len(runs) >= 2,
        )

    def verification(self, runs: Sequence[ConfigurationRunEvidence]) -> DimensionComparison:
        values: Dict[str, Any] = {}
        scored: List[Tuple[str, float]] = []
        for r in runs:
            v_cost = r.verification_cost_usd
            # Higher reliability + success with less repair is better verification outcome
            success_component = 1.0 if (r.succeeded or r.task_success) else 0.0
            repair_penalty = min(0.5, 0.1 * r.repair_count)
            score = max(0.0, success_component - repair_penalty)
            values[r.configuration_id] = {
                "verification_outcome_score": score,
                "repair_count": r.repair_count,
                "verification_cost_usd": v_cost,
            }
            scored.append((r.configuration_id, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        ranking = [c for c, _ in scored]
        return DimensionComparison(
            dimension="verification",
            values=values,
            ranking=ranking,
            best_configuration_id=ranking[0] if ranking else None,
            comparable=True,
        )

    def recovery(self, runs: Sequence[ConfigurationRunEvidence]) -> DimensionComparison:
        values: Dict[str, Any] = {}
        scored: List[Tuple[str, float]] = []
        for r in runs:
            # Fewer repairs and lower recovery cost rank better when success holds
            recovery_cost = r.recovery_cost_usd if r.recovery_cost_usd is not None else 0.0
            score = (1.0 if r.succeeded else 0.0) - 0.05 * r.repair_count - min(0.3, recovery_cost)
            values[r.configuration_id] = {
                "repair_count": r.repair_count,
                "recovery_cost_usd": r.recovery_cost_usd,
                "recovery_score": round(score, 6),
            }
            scored.append((r.configuration_id, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        ranking = [c for c, _ in scored]
        return DimensionComparison(
            dimension="recovery",
            values=values,
            ranking=ranking,
            best_configuration_id=ranking[0] if ranking else None,
            comparable=True,
        )