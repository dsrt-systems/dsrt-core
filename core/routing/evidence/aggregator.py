# core/routing/evidence/aggregator.py
"""
C9 Evidence Aggregator (§25).

Aggregates multiple ``RoutingEvidence`` observations into a single
``AggregatedEvidence`` per candidate, applying freshness decay and
computing confidence from sample depth + recency.

Key principle: **each dimension is retained separately** — the
aggregator does not collapse everything to one opaque score.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.routing.contracts import AggregatedEvidence, RoutingEvidence
from core.routing.enums import EvidenceConfidence
from core.routing.evidence.freshness import EvidenceFreshnessChecker


class EvidenceAggregator:
    """Aggregates routing evidence with freshness and uncertainty (§25).

    Args:
        freshness_checker: Checker instance.  A default is created
            if not supplied.
        min_samples_high: Total samples needed for HIGH confidence.
        min_samples_medium: Total samples needed for MEDIUM confidence.
        min_samples_low: Total samples needed for LOW confidence.
        min_freshness_high: Minimum freshness weight for HIGH.
        min_freshness_medium: Minimum freshness weight for MEDIUM.
    """

    def __init__(
        self,
        freshness_checker: EvidenceFreshnessChecker | None = None,
        *,
        min_samples_high: int = 50,
        min_samples_medium: int = 10,
        min_samples_low: int = 3,
        min_freshness_high: float = 0.7,
        min_freshness_medium: float = 0.4,
    ) -> None:
        self._checker = freshness_checker or EvidenceFreshnessChecker()
        self._min_high = min_samples_high
        self._min_med = min_samples_medium
        self._min_low = min_samples_low
        self._fresh_high = min_freshness_high
        self._fresh_med = min_freshness_medium

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def aggregate(
        self,
        candidate_key: str,
        evidence_list: list[RoutingEvidence],
        *,
        current_versions: dict[str, str] | None = None,
        now: datetime | None = None,
    ) -> AggregatedEvidence:
        """Aggregate evidence for a single candidate.

        Args:
            candidate_key: Unique identifier for the candidate
                (e.g. ``"agent_v1:model_v2:world_v3"``).
            evidence_list: All evidence observations for this candidate.
            current_versions: Optional dict with keys
                ``model``, ``agent``, ``world``, ``benchmark``
                for freshness checking.
            now: Override current time for deterministic tests.

        Returns:
            ``AggregatedEvidence`` with weighted metrics and confidence.
        """
        if not candidate_key:
            raise ValueError("candidate_key must be non-empty")

        if not evidence_list:
            return AggregatedEvidence(
                candidate_key=candidate_key,
                sources=[],
                aggregated_metrics={},
                total_sample_count=0,
                freshness_weight=0.0,
                confidence=EvidenceConfidence.INSUFFICIENT,
            )

        ref = now or datetime.now(timezone.utc)
        versions = current_versions or {}

        # ── Per-evidence freshness ───────────────────────────────
        weighted_metrics: dict[str, list[tuple[float, float]]] = {}
        total_samples = 0
        freshness_weights: list[float] = []

        for ev in evidence_list:
            fr = self._checker.check(
                ev,
                current_model_version=versions.get("model"),
                current_agent_version=versions.get("agent"),
                current_world_version=versions.get("world"),
                current_benchmark_version=versions.get("benchmark"),
                now=ref,
            )
            fw = fr.freshness_weight
            freshness_weights.append(fw)

            weighted_samples = ev.sample_count * fw
            total_samples += int(round(weighted_samples))

            for metric_key, metric_val in ev.metrics.items():
                if isinstance(metric_val, (int, float)):
                    if metric_key not in weighted_metrics:
                        weighted_metrics[metric_key] = []
                    weighted_metrics[metric_key].append(
                        (float(metric_val), fw)
                    )

        # ── Aggregate metrics (freshness-weighted mean) ──────────
        aggregated: dict[str, Any] = {}
        for key, pairs in weighted_metrics.items():
            total_w = sum(w for _, w in pairs)
            if total_w > 0:
                aggregated[key] = round(
                    sum(v * w for v, w in pairs) / total_w, 6
                )
            else:
                aggregated[key] = 0.0

        # ── Freshness ────────────────────────────────────────────
        avg_freshness = (
            sum(freshness_weights) / len(freshness_weights)
            if freshness_weights
            else 0.0
        )

        # ── Confidence ───────────────────────────────────────────
        confidence = self._compute_confidence(total_samples, avg_freshness)

        return AggregatedEvidence(
            candidate_key=candidate_key,
            sources=list(evidence_list),
            aggregated_metrics=aggregated,
            total_sample_count=total_samples,
            freshness_weight=round(avg_freshness, 4),
            confidence=confidence,
        )

    # ------------------------------------------------------------------
    # Confidence logic
    # ------------------------------------------------------------------

    def _compute_confidence(
        self, total_samples: int, avg_freshness: float
    ) -> EvidenceConfidence:
        """Derive confidence from sample depth + freshness (§25)."""
        if (
            total_samples >= self._min_high
            and avg_freshness >= self._fresh_high
        ):
            return EvidenceConfidence.HIGH
        if (
            total_samples >= self._min_med
            and avg_freshness >= self._fresh_med
        ):
            return EvidenceConfidence.MEDIUM
        if total_samples >= self._min_low:
            return EvidenceConfidence.LOW
        return EvidenceConfidence.INSUFFICIENT