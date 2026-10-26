# core/routing/selector/selector.py
"""
C9 Route Selector (§23).

Selects the best candidate from a set of evaluated routes using
weighted composite scoring.  Ties are broken deterministically by
candidate_id to ensure reproducibility (§59).
"""

from __future__ import annotations

from core.routing.contracts import RouteEvaluation
from core.routing.types import DimensionScores


class RouteSelector:
    """Selects the optimal route from evaluated candidates (§23).

    The selector does **not** collapse dimensions permanently.  It
    computes a weighted composite *only* for ranking; the full
    ``RouteEvaluation`` with per-dimension scores is preserved in
    the decision record.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def select(
        self,
        evaluations: list[RouteEvaluation],
        weights: DimensionScores,
    ) -> RouteEvaluation | None:
        """Select the best-evaluated candidate.

        Args:
            evaluations: Non-empty list of ``RouteEvaluation``.
            weights: Dimension weights from ``RoutingPreferences.weights()``.

        Returns:
            The top-ranked ``RouteEvaluation``, or ``None`` if the
            input list is empty.
        """
        if not evaluations:
            return None

        ranked = self.rank(evaluations, weights)
        return ranked[0] if ranked else None

    def rank(
        self,
        evaluations: list[RouteEvaluation],
        weights: DimensionScores,
    ) -> list[RouteEvaluation]:
        """Rank evaluations by weighted composite score.

        Ties are broken by ``candidate_id`` (lexicographic) for
        deterministic reproducibility.

        Returns:
            Evaluations sorted best-first.
        """
        def sort_key(ev: RouteEvaluation) -> tuple[float, str]:
            score = ev.weighted_score(weights)
            # Negate score so highest comes first; candidate_id for tie-break
            return (-score, ev.candidate_id)

        return sorted(evaluations, key=sort_key)

    def select_top_n(
        self,
        evaluations: list[RouteEvaluation],
        weights: DimensionScores,
        n: int = 3,
    ) -> list[RouteEvaluation]:
        """Return the top-N evaluated candidates.

        Useful for fallback chains (§39).
        """
        ranked = self.rank(evaluations, weights)
        return ranked[: max(1, n)]