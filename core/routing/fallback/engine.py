# core/routing/fallback/engine.py
"""
C9 Fallback Engine (§39–40).

Determines the appropriate fallback action when a route fails.
Fallback is not always model switching — possible responses include
retry, backoff, switch, delegate, replan, human approval, or abort.

Every fallback decision is recorded with full audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.routing.contracts import (
    FallbackPolicy,
    Route,
    RouteCandidate,
)
from core.routing.enums import FallbackActionType, FallbackTriggerType


@dataclass(frozen=True)
class FallbackDecision:
    """Outcome of a fallback evaluation."""

    trigger: FallbackTriggerType
    action: FallbackActionType
    policy_id: str
    attempt_number: int
    max_attempts: int
    next_model_id: str | None = None
    next_provider_id: str | None = None
    backoff_seconds: float = 0.0
    reason: str = ""
    decided_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def is_terminal(self) -> bool:
        """Whether this fallback ends the execution."""
        return self.action in (
            FallbackActionType.ABORT,
            FallbackActionType.HUMAN_APPROVAL,
        )


class FallbackEngine:
    """Evaluates and executes fallback policies (§39–40).

    Args:
        default_policy: Policy used when no explicit policy is
            attached to a route.
    """

    DEFAULT_POLICY = FallbackPolicy(
        policy_id="builtin_default_fallback",
        name="Default Fallback",
        triggers=list(FallbackTriggerType),
        action=FallbackActionType.RETRY,
        max_attempts=3,
        backoff_seconds=2.0,
    )

    def __init__(
        self,
        default_policy: FallbackPolicy | None = None,
    ) -> None:
        self._default = default_policy or self.DEFAULT_POLICY

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        trigger: FallbackTriggerType,
        current_route: Route,
        attempt_number: int = 1,
        policy: FallbackPolicy | None = None,
        fallback_candidates: list[RouteCandidate] | None = None,
    ) -> FallbackDecision:
        """Determine the fallback action for a route failure.

        Args:
            trigger: What caused the failure.
            current_route: The route that failed.
            attempt_number: Current fallback attempt (1-based).
            policy: Fallback policy (uses default if ``None``).
            fallback_candidates: Alternative candidates for switching.

        Returns:
            ``FallbackDecision`` describing what to do next.
        """
        pol = policy or self._default

        # Check if trigger is covered by the policy
        if pol.triggers and trigger not in pol.triggers:
            return FallbackDecision(
                trigger=trigger,
                action=FallbackActionType.ABORT,
                policy_id=pol.policy_id,
                attempt_number=attempt_number,
                max_attempts=pol.max_attempts,
                reason=(
                    f"Trigger {trigger.value} not covered by "
                    f"policy {pol.policy_id}"
                ),
            )

        # Check if we've exhausted attempts
        if attempt_number > pol.max_attempts:
            return FallbackDecision(
                trigger=trigger,
                action=FallbackActionType.ABORT,
                policy_id=pol.policy_id,
                attempt_number=attempt_number,
                max_attempts=pol.max_attempts,
                reason="Max fallback attempts exhausted",
            )

        # Determine action
        action = pol.action
        next_model = None
        next_provider = None
        backoff = 0.0

        if action == FallbackActionType.SWITCH_MODEL:
            next_model, next_provider = self._pick_fallback_model(
                current_route, fallback_candidates or [],
            )
            if next_model is None:
                action = FallbackActionType.ABORT
                reason = "No fallback model candidates available"
            else:
                reason = f"Switching to {next_model}"

        elif action == FallbackActionType.SWITCH_PROVIDER:
            next_model = current_route.model_id
            next_provider = self._pick_fallback_provider(
                current_route, fallback_candidates or [],
            )
            if next_provider is None:
                action = FallbackActionType.ABORT
                reason = "No fallback provider candidates available"
            else:
                reason = f"Switching to provider {next_provider}"

        elif action in (FallbackActionType.RETRY, FallbackActionType.BACKOFF):
            backoff = pol.backoff_seconds * attempt_number
            reason = f"Retry attempt {attempt_number}/{pol.max_attempts}"

        elif action == FallbackActionType.HUMAN_APPROVAL:
            reason = "Human approval required by policy"

        elif action == FallbackActionType.ABORT:
            reason = "Policy mandates abort"

        elif action == FallbackActionType.REPLAN:
            reason = "Replanning required"

        elif action == FallbackActionType.DELEGATE:
            reason = "Delegating to alternative agent"

        elif action == FallbackActionType.SWITCH_TOOL:
            reason = "Switching to alternative tool"

        else:
            reason = f"Action: {action.value}"

        return FallbackDecision(
            trigger=trigger,
            action=action,
            policy_id=pol.policy_id,
            attempt_number=attempt_number,
            max_attempts=pol.max_attempts,
            next_model_id=next_model,
            next_provider_id=next_provider,
            backoff_seconds=backoff,
            reason=reason,
        )

    def should_escalate(
        self,
        attempt_number: int,
        policy: FallbackPolicy | None = None,
    ) -> bool:
        """Check if fallback attempts have been exhausted."""
        pol = policy or self._default
        return attempt_number > pol.max_attempts

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pick_fallback_model(
        current: Route,
        candidates: list[RouteCandidate],
    ) -> tuple[str | None, str | None]:
        """Pick the first candidate model different from current."""
        for c in candidates:
            if not c.is_eligible:
                continue
            if c.model_id != current.model_id:
                return c.model_id, c.provider_id
        return None, None

    @staticmethod
    def _pick_fallback_provider(
        current: Route,
        candidates: list[RouteCandidate],
    ) -> str | None:
        """Pick the first candidate provider different from current."""
        for c in candidates:
            if not c.is_eligible:
                continue
            if c.provider_id != current.provider_id:
                return c.provider_id
        return None