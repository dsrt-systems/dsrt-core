# core/routing/selector/router.py
"""
C9 Intelligence Router (§3, §15).

The central orchestrator that ties together:
  - Capability matching  (C9.3)
  - Candidate generation (C9.4)
  - Policy filtering     (C9.4)
  - Evidence attachment  (C9.6)
  - Route evaluation     (C9.5)
  - Route selection      (C9.5)
  - Decision explanation (C9.5)

This is the single entry point for routing a task.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from core.routing.contracts import (
    AggregatedEvidence,
    AgentCapabilityProfile,
    ModelCapabilityProfile,
    Route,
    RouteCandidate,
    RouteDecision,
    RouteEvaluation,
    RoutingPolicy,
    RoutingProfile,
    TaskRequirements,
)
from core.routing.enums import EligibilityStatus, RoutingStatus
from core.routing.selector.evaluator import RouteEvaluator
from core.routing.selector.explainer import DecisionExplainer
from core.routing.selector.selector import RouteSelector


class IntelligenceRouter:
    """Central intelligence routing orchestrator (§3).

    Orchestrates the full routing pipeline from requirements to
    a selected route decision.

    Args:
        evaluator: Route evaluator instance.
        selector: Route selector instance.
        explainer: Decision explainer instance.
    """

    def __init__(
        self,
        evaluator: RouteEvaluator | None = None,
        selector: RouteSelector | None = None,
        explainer: DecisionExplainer | None = None,
    ) -> None:
        self._evaluator = evaluator or RouteEvaluator()
        self._selector = selector or RouteSelector()
        self._explainer = explainer or DecisionExplainer()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route(
        self,
        requirements: TaskRequirements,
        candidates: list[RouteCandidate],
        policy: RoutingPolicy | None = None,
        profile: RoutingProfile | None = None,
        evidence_map: dict[str, AggregatedEvidence] | None = None,
    ) -> RouteDecision:
        """Execute the full routing pipeline (§15).

        This method assumes candidates have already been generated
        and policy-filtered by the CandidateGenerator + PolicyEngine
        (C9.4).  It handles evaluation, selection, and explanation.

        Args:
            requirements: Structured task requirements.
            candidates: Pre-generated, policy-filtered candidates.
            policy: Active routing policy (for the decision record).
            profile: Active routing profile.
            evidence_map: ``{candidate_id: AggregatedEvidence}``.

        Returns:
            A complete ``RouteDecision`` with selected route,
            rejection details, evidence refs, and explanation.
        """
        decision_id = f"rtd_{uuid.uuid4().hex[:16]}"
        decision = RouteDecision(
            decision_id=decision_id,
            task_id=requirements.task_id,
            status=RoutingStatus.EVALUATING,
            requirements=requirements,
            routing_policy_id=policy.policy_id if policy else None,
            routing_policy_version=policy.version if policy else None,
            routing_profile_id=profile.profile_id if profile else None,
            candidates_considered=len(candidates),
        )

        # ── Separate eligible / rejected ─────────────────────
        eligible = [c for c in candidates if c.is_eligible]
        rejected = [c for c in candidates if not c.is_eligible]
        decision.candidates_eligible = len(eligible)

        for c in rejected:
            decision.rejected_candidates.append({
                "candidate_id": c.candidate_id,
                "category": (
                    c.rejections[0].category.value if c.rejections else "UNKNOWN"
                ),
                "detail": (
                    c.rejections[0].detail if c.rejections else ""
                ),
            })

        # ── Evaluate ─────────────────────────────────────────
        preferences = (
            profile.to_preferences()
            if profile
            else policy.preferences if policy else None
        )
        evaluations = self._evaluator.evaluate_all(
            eligible, evidence_map, preferences,
        )

        # ── Select ───────────────────────────────────────────
        decision.status = RoutingStatus.SELECTING
        weights = preferences.weights() if preferences else {
            "quality": 2.0, "cost": 2.0,
            "latency": 2.0, "reliability": 2.0,
        }

        best = self._selector.select(evaluations, weights)

        if best is None:
            decision.status = RoutingStatus.FAILED
            decision.decision_reason = {
                "reason": "no_eligible_candidates",
                "detail": (
                    f"All {len(candidates)} candidates were rejected "
                    f"by hard constraints."
                ),
            }
            return decision

        # ── Build selected Route ─────────────────────────────
        selected_candidate = next(
            c for c in eligible if c.candidate_id == best.candidate_id
        )
        decision.selected_route = Route(
            agent_id=selected_candidate.agent_id,
            agent_version_id=selected_candidate.agent_version_id,
            model_id=selected_candidate.model_id,
            model_version_id=selected_candidate.model_version_id,
            provider_id=selected_candidate.provider_id,
            world_id=selected_candidate.world_id,
            world_version_id=selected_candidate.world_version_id,
            tools=list(selected_candidate.tools),
        )
        decision.status = RoutingStatus.SELECTED

        # ── Evidence refs ────────────────────────────────────
        ev_map = evidence_map or {}
        ev_refs: list[str] = []
        for cid, ev in ev_map.items():
            for src in ev.sources:
                if src.benchmark_id:
                    ref = f"{src.benchmark_id}:{src.model_version}"
                    if ref not in ev_refs:
                        ev_refs.append(ref)
        decision.evidence_refs = ev_refs

        # ── Decision reason ──────────────────────────────────
        decision.decision_reason = {
            "selected_candidate": best.candidate_id,
            "quality_score": best.quality_score,
            "reliability_score": best.reliability_score,
            "latency_score": best.latency_score,
            "cost_score": best.cost_score,
            "weighted_score": round(best.weighted_score(weights), 4),
            "confidence": best.uncertainty.get("confidence", "UNKNOWN"),
            "explanation": self._explainer.explain(decision, evaluations),
        }

        # ── Configuration hash ───────────────────────────────
        decision.configuration_hash = self._config_hash(decision)

        return decision

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _config_hash(decision: RouteDecision) -> str:
        """Deterministic hash of the routing configuration."""
        route = decision.selected_route
        if not route:
            return ""
        canonical = {
            "agent": route.agent_version_id,
            "model": route.model_version_id,
            "provider": route.provider_id,
            "world": route.world_version_id,
            "tools": sorted(route.tools),
            "policy": decision.routing_policy_id,
            "profile": decision.routing_profile_id,
        }
        raw = json.dumps(canonical, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]