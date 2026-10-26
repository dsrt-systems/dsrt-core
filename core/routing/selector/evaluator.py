# core/routing/selector/evaluator.py
"""
C9 Route Evaluator (§23–24).

Scores eligible candidates across four independent dimensions:
  quality, reliability, latency, cost.

Each dimension is retained separately — no premature collapse to a
single opaque number.  A weighted composite is computed only at the
final selection step.

Evidence metrics are mapped to dimensions via a configurable key
mapping so the evaluator works with any Arena benchmark schema.
"""

from __future__ import annotations

from typing import Any

from core.routing.contracts import (
    AggregatedEvidence,
    RouteCandidate,
    RouteEvaluation,
    RoutingPreferences,
)
from core.routing.enums import EvidenceConfidence


# Default mapping: evidence metric key → routing dimension.
# Keys are matched case-insensitively; first match wins.
DEFAULT_METRIC_MAPPING: dict[str, list[str]] = {
    "quality": [
        "quality", "correctness", "accuracy", "f1",
        "pass_rate", "score", "task_success",
    ],
    "reliability": [
        "reliability", "consistency", "success_rate",
        "uptime", "completion_rate",
    ],
    "latency": [
        "latency", "response_time", "p50_latency",
        "p99_latency", "ttft",
    ],
    "cost": [
        "cost", "cost_per_token", "cost_per_call",
        "total_cost", "estimated_cost",
    ],
}

# Dimensions where *lower* is better (scores are inverted).
_INVERTED_DIMENSIONS = {"latency", "cost"}

# Confidence → numeric uncertainty penalty (subtracted from scores).
_CONFIDENCE_UNCERTAINTY: dict[EvidenceConfidence, float] = {
    EvidenceConfidence.HIGH: 0.0,
    EvidenceConfidence.MEDIUM: 0.1,
    EvidenceConfidence.LOW: 0.25,
    EvidenceConfidence.INSUFFICIENT: 0.5,
}


class RouteEvaluator:
    """Multi-dimensional candidate evaluator (§23–24).

    Args:
        metric_mapping: Override the default evidence-key → dimension
            mapping.  Keys are dimension names; values are lists of
            evidence metric keys to match (case-insensitive).
        default_score: Score assigned when no evidence is available
            for a dimension (0.0–1.0).
    """

    def __init__(
        self,
        metric_mapping: dict[str, list[str]] | None = None,
        default_score: float = 0.5,
    ) -> None:
        self._mapping = metric_mapping or DEFAULT_METRIC_MAPPING
        self._default = max(0.0, min(1.0, default_score))
        # Build reverse lookup: lowercased metric key → dimension
        self._reverse: dict[str, str] = {}
        for dim, keys in self._mapping.items():
            for k in keys:
                self._reverse[k.lower()] = dim

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        candidate: RouteCandidate,
        evidence: AggregatedEvidence | None = None,
        preferences: RoutingPreferences | None = None,
    ) -> RouteEvaluation:
        """Score a single candidate.

        Args:
            candidate: An *eligible* route candidate.
            evidence: Aggregated evidence for this candidate (may be
                ``None`` if no evidence exists).
            preferences: Routing preferences (currently unused in
                scoring but reserved for future dimension weighting
                inside the evaluator).

        Returns:
            ``RouteEvaluation`` with per-dimension scores, evidence
            payloads, and uncertainty estimates.
        """
        metrics = evidence.aggregated_metrics if evidence else {}
        confidence = (
            evidence.confidence
            if evidence
            else EvidenceConfidence.INSUFFICIENT
        )

        dim_scores = self._extract_dimension_scores(metrics)
        uncertainty_penalty = _CONFIDENCE_UNCERTAINTY.get(confidence, 0.5)

        quality = dim_scores.get("quality", self._default)
        reliability = dim_scores.get("reliability", self._default)
        latency = dim_scores.get("latency", self._default)
        cost = dim_scores.get("cost", self._default)

        # Apply uncertainty penalty (reduces scores when evidence is thin)
        quality = max(0.0, quality - uncertainty_penalty * 0.5)
        reliability = max(0.0, reliability - uncertainty_penalty * 0.5)

        return RouteEvaluation(
            candidate_id=candidate.candidate_id,
            quality_score=round(quality, 4),
            reliability_score=round(reliability, 4),
            latency_score=round(latency, 4),
            cost_score=round(cost, 4),
            quality_evidence=self._dim_evidence(metrics, "quality"),
            reliability_evidence=self._dim_evidence(metrics, "reliability"),
            estimated_latency=self._dim_evidence(metrics, "latency"),
            estimated_cost=self._dim_evidence(metrics, "cost"),
            constraint_fit=dict(candidate.constraint_fit),
            uncertainty={
                "confidence": confidence.value,
                "penalty": uncertainty_penalty,
                "sample_count": (
                    evidence.total_sample_count if evidence else 0
                ),
                "freshness_weight": (
                    evidence.freshness_weight if evidence else 0.0
                ),
            },
        )

    def evaluate_all(
        self,
        candidates: list[RouteCandidate],
        evidence_map: dict[str, AggregatedEvidence] | None = None,
        preferences: RoutingPreferences | None = None,
    ) -> list[RouteEvaluation]:
        """Evaluate a list of eligible candidates.

        Args:
            candidates: List of route candidates.
            evidence_map: Mapping of ``candidate_id → AggregatedEvidence``.
            preferences: Routing preferences.

        Returns:
            List of ``RouteEvaluation``, one per candidate.
        """
        ev_map = evidence_map or {}
        return [
            self.evaluate(c, ev_map.get(c.candidate_id), preferences)
            for c in candidates
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_dimension_scores(
        self, metrics: dict[str, Any]
    ) -> dict[str, float]:
        """Map evidence metrics to the four routing dimensions."""
        dim_values: dict[str, list[float]] = {
            "quality": [],
            "reliability": [],
            "latency": [],
            "cost": [],
        }

        for key, val in metrics.items():
            if not isinstance(val, (int, float)):
                continue
            # Skip consensus / metadata keys
            if key.endswith("_consensus"):
                continue
            dim = self._reverse.get(key.lower())
            if dim and dim in dim_values:
                dim_values[dim].append(float(val))

        scores: dict[str, float] = {}
        for dim, values in dim_values.items():
            if not values:
                continue
            raw = sum(values) / len(values)
            if dim in _INVERTED_DIMENSIONS:
                # Invert: assume values are normalised 0–1 where lower=better
                raw = max(0.0, 1.0 - raw)
            scores[dim] = max(0.0, min(1.0, raw))

        return scores

    def _dim_evidence(
        self, metrics: dict[str, Any], dimension: str
    ) -> dict[str, Any]:
        """Extract evidence metrics belonging to a dimension."""
        keys = {k.lower() for k in self._mapping.get(dimension, [])}
        return {
            k: v
            for k, v in metrics.items()
            if k.lower() in keys and isinstance(v, (int, float, str))
        }