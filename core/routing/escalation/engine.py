# core/routing/escalation/engine.py
"""
C9 Escalation Engine (§41).

Determines when human intervention is required during routing
or execution.  Critical for enterprise workflows where certain
failures must not be auto-resolved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.routing.contracts import EscalationPolicy, Route


@dataclass(frozen=True)
class EscalationDecision:
    """Outcome of an escalation evaluation."""

    should_escalate: bool
    reason: str
    policy_id: str
    route_model_id: str | None = None
    decided_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class EscalationEngine:
    """Evaluates whether human review is required (§41).

    Args:
        default_policy: Default escalation policy.
    """

    DEFAULT_POLICY = EscalationPolicy(
        policy_id="builtin_default_escalation",
        name="Default Escalation",
        max_fallback_attempts=3,
    )

    def __init__(
        self,
        default_policy: EscalationPolicy | None = None,
    ) -> None:
        self._default = default_policy or self.DEFAULT_POLICY

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        fallback_attempts: int,
        route: Route | None = None,
        policy: EscalationPolicy | None = None,
        is_security_sensitive: bool = False,
    ) -> EscalationDecision:
        """Determine if escalation to human review is needed.

        Args:
            fallback_attempts: Number of fallback attempts so far.
            route: Current route (for context in the decision).
            policy: Escalation policy (uses default if ``None``).
            is_security_sensitive: Whether the task involves
                security-sensitive operations.

        Returns:
            ``EscalationDecision`` with the verdict and reason.
        """
        pol = policy or self._default
        model_id = route.model_id if route else None

        if pol.should_escalate(fallback_attempts, is_security_sensitive):
            # Determine reason
            if pol.policy_mandated_review:
                reason = "Policy mandates human review for all routes"
            elif pol.security_sensitive and is_security_sensitive:
                reason = "Security-sensitive task requires human approval"
            elif fallback_attempts >= pol.max_fallback_attempts:
                reason = (
                    f"Fallback attempts ({fallback_attempts}) reached "
                    f"maximum ({pol.max_fallback_attempts})"
                )
            else:
                reason = "Escalation triggered"

            return EscalationDecision(
                should_escalate=True,
                reason=reason,
                policy_id=pol.policy_id,
                route_model_id=model_id,
            )

        return EscalationDecision(
            should_escalate=False,
            reason="No escalation needed",
            policy_id=pol.policy_id,
            route_model_id=model_id,
        )