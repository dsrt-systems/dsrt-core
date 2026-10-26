"""
C11.5 — Constraint Checker.

Evaluates candidate configurations against hard constraints:
    Q(θ) ≥ Q_min,  R(θ) ≥ R_min,  L(θ) ≤ L_max,  C(θ) ≤ B

A candidate that violates any hard constraint is INFEASIBLE and must
not be selected regardless of its objective score.
"""

from __future__ import annotations

import logging

from schemas.domain.economic_optimization import (
    CandidateFeasibility,
    ExecutionConfigCandidate,
    FeasibilityStatus,
    OptimizationConstraints,
)

logger = logging.getLogger(__name__)


class ConstraintChecker:
    """Check a single execution configuration against hard constraints."""

    def check(
        self,
        candidate: ExecutionConfigCandidate,
        constraints: OptimizationConstraints,
    ) -> CandidateFeasibility:
        violations: list[str] = []
        satisfied: list[str] = []

        # --- Quality constraint: Q(θ) ≥ Q_min ---
        if candidate.estimated_quality is not None:
            if candidate.estimated_quality < constraints.min_quality:
                violations.append(
                    f"quality {candidate.estimated_quality:.3f} < min {constraints.min_quality:.3f}"
                )
            else:
                satisfied.append("quality")
        else:
            # Unknown quality — do NOT auto-reject; mark as unknown
            satisfied.append("quality_unknown")

        # --- Reliability constraint: R(θ) ≥ R_min ---
        if candidate.estimated_reliability is not None:
            if candidate.estimated_reliability < constraints.min_reliability:
                violations.append(
                    f"reliability {candidate.estimated_reliability:.3f} < min {constraints.min_reliability:.3f}"
                )
            else:
                satisfied.append("reliability")
        else:
            satisfied.append("reliability_unknown")

        # --- Latency constraint: L(θ) ≤ L_max ---
        if constraints.max_latency_ms is not None:
            if candidate.estimated_latency_ms is not None:
                if candidate.estimated_latency_ms > constraints.max_latency_ms:
                    violations.append(
                        f"latency {candidate.estimated_latency_ms}ms > max {constraints.max_latency_ms}ms"
                    )
                else:
                    satisfied.append("latency")
            else:
                satisfied.append("latency_unknown")
        else:
            satisfied.append("latency_unconstrained")

        # --- Budget constraint: C(θ) ≤ B ---
        if constraints.max_budget is not None:
            total_cost = candidate.cost_breakdown.total
            if total_cost > constraints.max_budget:
                violations.append(
                    f"cost ${total_cost:.4f} > budget ${constraints.max_budget:.4f}"
                )
            else:
                satisfied.append("budget")
        else:
            satisfied.append("budget_unconstrained")

        # --- Determine status ---
        if not violations:
            status = FeasibilityStatus.FEASIBLE
        elif len(violations) == 1:
            # Map single violation to specific status
            v = violations[0]
            if "quality" in v:
                status = FeasibilityStatus.INFEASIBLE_QUALITY
            elif "reliability" in v:
                status = FeasibilityStatus.INFEASIBLE_RELIABILITY
            elif "latency" in v:
                status = FeasibilityStatus.INFEASIBLE_LATENCY
            elif "cost" in v or "budget" in v:
                status = FeasibilityStatus.INFEASIBLE_BUDGET
            else:
                status = FeasibilityStatus.INFEASIBLE_MULTIPLE
        else:
            status = FeasibilityStatus.INFEASIBLE_MULTIPLE

        result = CandidateFeasibility(
            candidate_id=candidate.candidate_id,
            status=status,
            violations=violations,
            satisfied_constraints=satisfied,
        )
        logger.debug("Feasibility %s: %s", candidate.candidate_id, status.value)
        return result