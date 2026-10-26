# core/routing/adaptive/controller.py
"""
C9 Adaptive Route Controller (§36–38).

Monitors execution observations and triggers route re-evaluation
when the current route is no longer valid.  Route changes are
always recorded — never silently switched.

Key principle: canonical DSRT state (C4) is preserved across
model switches via the Context Compiler.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.routing.contracts import (
    AdaptiveRoute,
    Route,
    RouteChangeRecord,
    RouteCandidate,
)
from core.routing.enums import (
    AdaptiveRouteState,
    FallbackActionType,
    FallbackTriggerType,
)
from core.routing.escalation.engine import EscalationDecision, EscalationEngine
from core.routing.fallback.engine import FallbackDecision, FallbackEngine


@dataclass
class AdaptationResult:
    """Outcome of an adaptation cycle."""

    action_taken: str
    new_route: Route | None = None
    fallback_decision: FallbackDecision | None = None
    escalation_decision: EscalationDecision | None = None
    change_record: RouteChangeRecord | None = None
    reason: str = ""


class AdaptiveRouteController:
    """Manages mid-execution route adaptation (§36–38).

    Wraps the fallback and escalation engines to provide a unified
    adaptation interface.

    Args:
        fallback_engine: Fallback policy evaluator.
        escalation_engine: Escalation policy evaluator.
        max_re_evaluations: Maximum number of re-evaluation cycles
            to prevent infinite loops.
    """

    def __init__(
        self,
        fallback_engine: FallbackEngine | None = None,
        escalation_engine: EscalationEngine | None = None,
        max_re_evaluations: int = 5,
    ) -> None:
        self._fallback = fallback_engine or FallbackEngine()
        self._escalation = escalation_engine or EscalationEngine()
        self._max_re_eval = max_re_evaluations

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_adaptive_route(
        self,
        route: Route,
        max_fallback_attempts: int = 3,
    ) -> AdaptiveRoute:
        """Wrap a selected route in an adaptive container."""
        return AdaptiveRoute(
            current_route=route,
            state=AdaptiveRouteState.ACTIVE,
            max_fallback_attempts=max_fallback_attempts,
        )

    def on_observation(
        self,
        adaptive: AdaptiveRoute,
        trigger: FallbackTriggerType,
        observation: dict[str, Any] | None = None,
        fallback_candidates: list[RouteCandidate] | None = None,
        is_security_sensitive: bool = False,
    ) -> AdaptationResult:
        """React to an execution observation that may require adaptation.

        This is the main entry point called during execution when
        something goes wrong (timeout, verification failure, etc.).

        Args:
            adaptive: The current adaptive route state.
            trigger: What went wrong.
            observation: Optional observation details.
            fallback_candidates: Alternative candidates for switching.
            is_security_sensitive: Security context.

        Returns:
            ``AdaptationResult`` describing what happened.
        """
        # Guard: already aborted or escalated
        if adaptive.state in (
            AdaptiveRouteState.ABORTED,
            AdaptiveRouteState.ESCALATED,
        ):
            return AdaptationResult(
                action_taken="no_action",
                reason=f"Route already in terminal state: {adaptive.state.value}",
            )

        # Guard: re-evaluation limit
        if adaptive.fallback_attempts >= self._max_re_eval:
            adaptive.state = AdaptiveRouteState.ABORTED
            return AdaptationResult(
                action_taken="aborted",
                reason="Maximum re-evaluation limit reached",
            )

        adaptive.state = AdaptiveRouteState.EVALUATING

        # ── Fallback evaluation ──────────────────────────────
        fb_decision = self._fallback.evaluate(
            trigger=trigger,
            current_route=adaptive.current_route,
            attempt_number=adaptive.fallback_attempts + 1,
            fallback_candidates=fallback_candidates,
        )

        # ── Check escalation ─────────────────────────────────
        esc_decision = self._escalation.evaluate(
            fallback_attempts=adaptive.fallback_attempts + 1,
            route=adaptive.current_route,
            is_security_sensitive=is_security_sensitive,
        )

        if esc_decision.should_escalate:
            adaptive.state = AdaptiveRouteState.ESCALATED
            return AdaptationResult(
                action_taken="escalated",
                escalation_decision=esc_decision,
                fallback_decision=fb_decision,
                reason=esc_decision.reason,
            )

        # ── Apply fallback action ────────────────────────────
        if fb_decision.is_terminal:
            adaptive.state = AdaptiveRouteState.ABORTED
            return AdaptationResult(
                action_taken="aborted",
                fallback_decision=fb_decision,
                reason=fb_decision.reason,
            )

        if fb_decision.action in (
            FallbackActionType.SWITCH_MODEL,
            FallbackActionType.SWITCH_PROVIDER,
        ):
            return self._apply_switch(adaptive, fb_decision)

        # Retry / backoff / replan / delegate / switch_tool
        adaptive.state = AdaptiveRouteState.ACTIVE
        return AdaptationResult(
            action_taken=fb_decision.action.value,
            fallback_decision=fb_decision,
            reason=fb_decision.reason,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _apply_switch(
        self,
        adaptive: AdaptiveRoute,
        fb: FallbackDecision,
    ) -> AdaptationResult:
        """Apply a model or provider switch to the adaptive route."""
        old_route = adaptive.current_route
        old_model = old_route.model_id

        new_model = fb.next_model_id or old_route.model_id
        new_provider = fb.next_provider_id or old_route.provider_id

        new_route = Route(
            agent_id=old_route.agent_id,
            agent_version_id=old_route.agent_version_id,
            model_id=new_model,
            model_version_id=old_route.model_version_id,
            provider_id=new_provider,
            world_id=old_route.world_id,
            world_version_id=old_route.world_version_id,
            tools=list(old_route.tools),
            context_profile=old_route.context_profile,
            verification_policy=old_route.verification_policy,
            execution_strategy=old_route.execution_strategy,
            fallback_policy_id=old_route.fallback_policy_id,
        )

        change = RouteChangeRecord(
            from_model_id=old_model,
            to_model_id=new_model,
            reason=fb.reason,
            trigger_type=fb.trigger,
            policy_id=fb.policy_id,
        )

        adaptive.current_route = new_route
        adaptive.record_change(change)
        adaptive.state = AdaptiveRouteState.ACTIVE

        return AdaptationResult(
            action_taken="switched",
            new_route=new_route,
            fallback_decision=fb,
            change_record=change,
            reason=fb.reason,
        )