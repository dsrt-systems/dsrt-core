# core/routing/selector/explainer.py
"""
C9 Decision Explainer (§18).

Produces structured, human-readable explanations of why a route
was selected.  Critical for enterprise trust and auditability.

The explanation answers:
  - What was required?
  - What constraints applied?
  - What evidence was considered?
  - Why were alternatives rejected?
  - Why was this route selected?
"""

from __future__ import annotations

from typing import Any

from core.routing.contracts import RouteDecision, RouteEvaluation


class DecisionExplainer:
    """Generates structured routing decision explanations (§18)."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def explain(
        self,
        decision: RouteDecision,
        evaluations: list[RouteEvaluation] | None = None,
    ) -> dict[str, Any]:
        """Build a structured explanation for a routing decision.

        Args:
            decision: The completed ``RouteDecision``.
            evaluations: Optional list of evaluations for richer
                context.

        Returns:
            A JSON-serialisable dict with the explanation.
        """
        explanation: dict[str, Any] = {
            "decision_id": decision.decision_id,
            "task_id": decision.task_id,
            "status": decision.status.value,
        }

        # ── Requirements summary ─────────────────────────────
        if decision.requirements:
            req = decision.requirements
            explanation["required"] = {
                "domain": req.classification.primary_domain.value,
                "capabilities": [
                    c.capability_id for c in req.required_capabilities
                ],
                "quality": req.quality.overall.value,
                "security": {
                    "external_write": req.security.external_write_actions,
                    "sandbox": req.security.requires_sandbox,
                },
            }
            if req.resources.max_cost_usd is not None:
                explanation["required"]["max_cost_usd"] = (
                    req.resources.max_cost_usd
                )
            if req.resources.max_duration_seconds is not None:
                explanation["required"]["max_duration_seconds"] = (
                    req.resources.max_duration_seconds
                )

        # ── Constraints applied ──────────────────────────────
        if decision.routing_policy_id:
            explanation["constraints"] = {
                "policy_id": decision.routing_policy_id,
                "policy_version": decision.routing_policy_version,
                "profile_id": decision.routing_profile_id,
            }

        # ── Selection summary ────────────────────────────────
        if decision.selected_route:
            route = decision.selected_route
            explanation["selected"] = {
                "agent": f"{route.agent_id}@{route.agent_version_id}",
                "model": f"{route.model_id}@{route.model_version_id}",
                "provider": route.provider_id,
                "world": (
                    f"{route.world_id}@{route.world_version_id}"
                    if route.world_id
                    else None
                ),
                "tools": route.tools,
            }

        # ── Candidate statistics ─────────────────────────────
        explanation["candidates"] = {
            "considered": decision.candidates_considered,
            "eligible": decision.candidates_eligible,
            "rejected": len(decision.rejected_candidates),
        }

        # ── Rejection reasons ────────────────────────────────
        if decision.rejected_candidates:
            rejection_summary: dict[str, int] = {}
            for rej in decision.rejected_candidates:
                cat = rej.get("category", "UNKNOWN")
                rejection_summary[cat] = rejection_summary.get(cat, 0) + 1
            explanation["rejection_summary"] = rejection_summary

        # ── Evidence ─────────────────────────────────────────
        if decision.evidence_refs:
            explanation["evidence_refs"] = decision.evidence_refs

        # ── Decision reason (from the router) ────────────────
        if decision.decision_reason:
            explanation["reason"] = decision.decision_reason

        # ── Top evaluations (if provided) ────────────────────
        if evaluations:
            top = sorted(
                evaluations,
                key=lambda e: (
                    -(e.quality_score + e.reliability_score),
                    e.candidate_id,
                ),
            )[:3]
            explanation["top_evaluations"] = [
                {
                    "candidate_id": e.candidate_id,
                    "quality": e.quality_score,
                    "reliability": e.reliability_score,
                    "latency": e.latency_score,
                    "cost": e.cost_score,
                    "uncertainty": e.uncertainty.get("confidence"),
                }
                for e in top
            ]

        return explanation

    def explain_text(
        self,
        decision: RouteDecision,
        evaluations: list[RouteEvaluation] | None = None,
    ) -> str:
        """Produce a plain-text explanation suitable for logging."""
        data = self.explain(decision, evaluations)

        lines = [
            f"Route Decision {data['decision_id']} for task {data['task_id']}",
            f"Status: {data['status']}",
        ]

        if "required" in data:
            req = data["required"]
            lines.append(f"Domain: {req['domain']}")
            lines.append(f"Capabilities: {', '.join(req['capabilities'])}")
            lines.append(f"Quality: {req['quality']}")

        if "selected" in data:
            sel = data["selected"]
            lines.append(f"Selected: {sel['model']} via {sel['provider']}")

        cands = data.get("candidates", {})
        lines.append(
            f"Candidates: {cands.get('considered', 0)} considered, "
            f"{cands.get('eligible', 0)} eligible, "
            f"{cands.get('rejected', 0)} rejected"
        )

        if "reason" in data:
            lines.append(f"Reason: {data['reason']}")

        return "\n".join(lines)