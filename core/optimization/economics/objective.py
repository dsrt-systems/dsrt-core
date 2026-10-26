"""
C11.5 — Objective Scorer.

Computes a composite objective score for feasible candidates
using policy-weighted combination of normalised sub-scores.

    objective = w_q·S_quality + w_r·S_reliability + w_c·S_cost + w_l·S_latency − penalty

Policy weights (spec §6C):

    Economy:  cost-dominant
    Balanced: equal balance
    Quality:  quality+reliability-dominant
"""

from __future__ import annotations

import logging
import math

from schemas.domain.economic_optimization import (
    CandidateFeasibility,
    ExecutionConfigCandidate,
    FeasibilityStatus,
    OptimizationPolicy,
    ScoredCandidate,
)

logger = logging.getLogger(__name__)

# Policy weight vectors: (quality, reliability, cost, latency)
_POLICY_WEIGHTS: dict[OptimizationPolicy, tuple[float, float, float, float]] = {
    OptimizationPolicy.ECONOMY: (0.15, 0.15, 0.55, 0.15),
    OptimizationPolicy.BALANCED: (0.30, 0.25, 0.25, 0.20),
    OptimizationPolicy.QUALITY: (0.40, 0.30, 0.15, 0.15),
}

# Maximum expected values for normalisation
_MAX_COST = 1.0        # $1.00 — costs above this score 0
_MAX_LATENCY = 600_000  # 10 minutes in ms


class ObjectiveScorer:
    """Score feasible candidates under a given optimisation policy."""

    def __init__(
        self,
        max_cost: float = _MAX_COST,
        max_latency_ms: int = _MAX_LATENCY,
        evidence_confidence_floor: float = 0.3,
    ) -> None:
        self._max_cost = max_cost
        self._max_latency = max_latency_ms
        self._confidence_floor = evidence_confidence_floor

    def score(
        self,
        candidate: ExecutionConfigCandidate,
        feasibility: CandidateFeasibility,
        policy: OptimizationPolicy = OptimizationPolicy.BALANCED,
    ) -> ScoredCandidate:
        """
        Produce a ScoredCandidate.  Infeasible candidates receive score 0.
        """
        if feasibility.status != FeasibilityStatus.FEASIBLE:
            return ScoredCandidate(
                candidate_id=candidate.candidate_id,
                feasibility=feasibility,
                objective_score=0.0,
            )

        wq, wr, wc, wl = _POLICY_WEIGHTS[policy]

        q_score = self._quality_score(candidate)
        r_score = self._reliability_score(candidate)
        c_score = self._cost_score(candidate)
        l_score = self._latency_score(candidate)
        penalty = self._evidence_penalty(candidate)

        raw = wq * q_score + wr * r_score + wc * c_score + wl * l_score
        objective = max(0.0, raw - penalty)

        scored = ScoredCandidate(
            candidate_id=candidate.candidate_id,
            feasibility=feasibility,
            objective_score=round(objective, 6),
            quality_score=round(q_score, 6),
            reliability_score=round(r_score, 6),
            cost_score=round(c_score, 6),
            latency_score=round(l_score, 6),
            evidence_penalty=round(penalty, 6),
            score_components={
                "w_quality": wq,
                "w_reliability": wr,
                "w_cost": wc,
                "w_latency": wl,
                "raw_weighted": round(raw, 6),
                "penalty": round(penalty, 6),
            },
        )
        logger.debug(
            "Score %s: obj=%.4f (q=%.2f r=%.2f c=%.2f l=%.2f pen=%.3f)",
            candidate.candidate_id, objective, q_score, r_score, c_score, l_score, penalty,
        )
        return scored

    # ------------------------------------------------------------------
    # Sub-score functions (all return 0..1, higher = better)
    # ------------------------------------------------------------------

    def _quality_score(self, c: ExecutionConfigCandidate) -> float:
        if c.estimated_quality is not None:
            return min(1.0, max(0.0, c.estimated_quality))
        return 0.5  # uninformed prior

    def _reliability_score(self, c: ExecutionConfigCandidate) -> float:
        if c.estimated_reliability is not None:
            return min(1.0, max(0.0, c.estimated_reliability))
        return 0.5

    def _cost_score(self, c: ExecutionConfigCandidate) -> float:
        """Lower cost → higher score.  Uses 1 - cost/max_cost."""
        total = c.cost_breakdown.total
        if total <= 0:
            return 1.0
        ratio = total / self._max_cost
        return max(0.0, 1.0 - ratio)

    def _latency_score(self, c: ExecutionConfigCandidate) -> float:
        if c.estimated_latency_ms is None:
            return 0.5
        if c.estimated_latency_ms <= 0:
            return 1.0
        ratio = c.estimated_latency_ms / self._max_latency
        return max(0.0, 1.0 - ratio)

    def _evidence_penalty(self, c: ExecutionConfigCandidate) -> float:
        """
        Apply a penalty when evidence is thin.
        This discourages selecting candidates whose estimates are unreliable.
        Penalty = max_penalty × (1 − confidence), scaled by a log-sample
        size factor.
        """
        max_penalty = 0.10
        confidence = c.evidence_confidence if c.evidence_confidence is not None else 0.0
        sample = max(1, c.evidence_sample_size)

        # Confidence factor (0 = no confidence, 1 = full)
        conf_factor = min(1.0, confidence)

        # Sample-size factor: log2(sample)/log2(100) capped at 1
        sample_factor = min(1.0, math.log2(sample) / math.log2(100))

        combined = (conf_factor + sample_factor) / 2.0
        penalty = max_penalty * (1.0 - combined)
        return max(0.0, penalty)