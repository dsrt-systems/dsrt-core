# core/routing/policies/engine.py
"""
C9 Policy Engine (§14, §19–22).

Combines hard constraint filtering and soft preference scoring
into a single pipeline step.

Flow:
  1. Apply hard constraints → reject ineligible candidates.
  2. Score eligible candidates on soft preferences.
  3. Return filtered + scored candidate list.
"""

from __future__ import annotations

from core.routing.contracts import (
    RouteCandidate,
    RoutingPolicy,
    RoutingPreferences,
    RoutingProfile,
    TaskRequirements,
)
from core.routing.policies.constraints import HardConstraintChecker
from core.routing.policies.preferences import PreferenceScorer


class PolicyEngine:
    """Applies routing policies to candidate lists (§19).

    Usage::

        engine = PolicyEngine()
        eligible, rejected = engine.apply(
            candidates=candidates,
            policy=policy,
            requirements=requirements,
        )
    """

    def __init__(
        self,
        constraint_checker: HardConstraintChecker | None = None,
        preference_scorer: PreferenceScorer | None = None,
    ) -> None:
        self._checker = constraint_checker or HardConstraintChecker()
        self._scorer = preference_scorer or PreferenceScorer()

    def apply(
        self,
        candidates: list[RouteCandidate],
        policy: RoutingPolicy,
        requirements: TaskRequirements,
        profile: RoutingProfile | None = None,
        evidence_map: dict[str, dict[str, float]] | None = None,
    ) -> tuple[list[RouteCandidate], list[RouteCandidate]]:
        """Filter and score candidates.

        Parameters
        ----------
        candidates:
            All generated candidates.
        policy:
            The active routing policy (constraints + preferences).
        requirements:
            The task requirements.
        profile:
            Optional routing profile that overrides policy preferences.
        evidence_map:
            Optional evidence scores keyed by candidate_id.

        Returns
        -------
        tuple[list[RouteCandidate], list[RouteCandidate]]
            (eligible_candidates, rejected_candidates)
        """
        # Merge profile preferences over policy preferences
        if profile is not None:
            preferences = profile.to_preferences()
        else:
            preferences = policy.preferences

        eligible: list[RouteCandidate] = []
        rejected: list[RouteCandidate] = []

        # ── Phase 1: Hard constraint filtering ────────────────
        for candidate in candidates:
            # Skip already-rejected candidates (e.g. from CandidateGenerator)
            if not candidate.is_eligible:
                rejected.append(candidate)
                continue

            passed = self._checker.check_all(
                candidate, policy.constraints, requirements
            )
            if passed:
                eligible.append(candidate)
            else:
                rejected.append(candidate)

        # ── Phase 2: Soft preference scoring ──────────────────
        evidence_map = evidence_map or {}
        for candidate in eligible:
            ev = evidence_map.get(candidate.candidate_id, {})
            scores = self._scorer.score_candidate(
                candidate, preferences, ev
            )
            # Store scores in constraint_fit for downstream use
            candidate.constraint_fit["preference_scores"] = scores

        return eligible, rejected

    def filter_only(
        self,
        candidates: list[RouteCandidate],
        policy: RoutingPolicy,
        requirements: TaskRequirements,
    ) -> tuple[list[RouteCandidate], list[RouteCandidate]]:
        """Hard-constraint filtering only, no scoring."""
        eligible: list[RouteCandidate] = []
        rejected: list[RouteCandidate] = []

        for candidate in candidates:
            if not candidate.is_eligible:
                rejected.append(candidate)
                continue
            if self._checker.check_all(
                candidate, policy.constraints, requirements
            ):
                eligible.append(candidate)
            else:
                rejected.append(candidate)

        return eligible, rejected