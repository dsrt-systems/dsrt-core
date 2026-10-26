# core/routing/policies/preferences.py
"""
C9 Soft Preference Scorer (§14, §23–24).

Scores eligible candidates on soft dimensions:
  quality, cost, latency, reliability.

These scores are used by the RouteSelector (C9.5) for final
ranking.  The PolicyEngine attaches them to candidates but
does NOT reject based on soft preferences.
"""

from __future__ import annotations

from core.routing.contracts import (
    RouteCandidate,
    RoutingPreferences,
)
from core.routing.enums import RoutingPriority


# Priority → numeric weight mapping
_PRIORITY_WEIGHT = {
    RoutingPriority.HIGH: 3.0,
    RoutingPriority.MEDIUM: 2.0,
    RoutingPriority.LOW: 1.0,
    RoutingPriority.NONE: 0.0,
}


class PreferenceScorer:
    """Scores candidates on soft preference dimensions (§23)."""

    def score_candidate(
        self,
        candidate: RouteCandidate,
        preferences: RoutingPreferences,
        evidence_scores: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """Compute per-dimension preference scores for a candidate.

        Parameters
        ----------
        candidate:
            The route candidate to score.
        preferences:
            The routing preferences (priority weights).
        evidence_scores:
            Optional pre-computed evidence scores from C8.
            Keys: ``quality``, ``reliability``, ``latency``, ``cost``.
            Values: 0.0 to 1.0.

        Returns
        -------
        dict[str, float]
            Weighted scores per dimension.
        """
        evidence = evidence_scores or {}
        weights = preferences.weights()

        scores: dict[str, float] = {}

        # Quality: from evidence or capability fit
        quality_raw = evidence.get(
            "quality",
            self._estimate_quality(candidate),
        )
        scores["quality"] = quality_raw * weights.get("quality", 0.0)

        # Reliability: from evidence
        reliability_raw = evidence.get("reliability", 0.5)
        scores["reliability"] = reliability_raw * weights.get("reliability", 0.0)

        # Latency: lower is better, invert
        latency_raw = evidence.get("latency", 0.5)
        scores["latency"] = latency_raw * weights.get("latency", 0.0)

        # Cost: lower is better, invert
        cost_raw = evidence.get("cost", 0.5)
        scores["cost"] = cost_raw * weights.get("cost", 0.0)

        return scores

    def _estimate_quality(self, candidate: RouteCandidate) -> float:
        """Heuristic quality estimate from capability fit.

        This is a placeholder until C9.6 EvidenceEngine provides
        real Arena evidence scores.
        """
        if not candidate.capability_fit:
            return 0.5

        matched = sum(1 for v in candidate.capability_fit.values() if v)
        total = len(candidate.capability_fit)
        return matched / max(total, 1)

    def rank_candidates(
        self,
        candidates: list[RouteCandidate],
        preferences: RoutingPreferences,
        evidence_map: dict[str, dict[str, float]] | None = None,
    ) -> list[tuple[RouteCandidate, float]]:
        """Rank eligible candidates by total weighted preference score.

        Returns list of (candidate, total_score) sorted descending.
        """
        evidence_map = evidence_map or {}
        ranked: list[tuple[RouteCandidate, float]] = []

        for c in candidates:
            if not c.is_eligible:
                continue
            ev = evidence_map.get(c.candidate_id, {})
            scores = self.score_candidate(c, preferences, ev)
            total = sum(scores.values())
            ranked.append((c, total))

        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked