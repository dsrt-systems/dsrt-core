"""
C6 Recovery Decider (C6 §38-41).

Determines the appropriate recovery action when verification fails.
Bridges C6 verification results to C5 recovery mechanisms.

Recovery Loop (C6 §40):
    EXECUTE → OBSERVE → VERIFY → CLASSIFY → RECOVER → REVERIFY → ACCEPT

Bounded by policy (C6 §41):
    max_verification_attempts: 3
    max_recovery_cycles: 3
    max_replans: 5
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from schemas.domain.enums import (
    IncidentCategory,
    IncidentSeverity,
    VerificationAction,
    VerificationStatus,
)
from schemas.domain.verification import (
    C6RecoveryDecision,
    C6VerificationResult,
    VerificationCheckResult,
    VerificationPolicy,
)

from core.observability.logging import get_logger
from core.verification.reliability.classifier import (
    FailureClassification,
    FailureClassifier,
)


logger = get_logger("dsrt.verification.recovery")


@dataclass
class RecoveryContext:
    """Context for making a recovery decision."""
    verification_result: C6VerificationResult
    policy: VerificationPolicy
    attempt_number: int = 1
    recovery_cycle: int = 0
    replan_count: int = 0
    previous_actions: list[str] = field(default_factory=list)
    execution_id: str = ""
    node_execution_id: str | None = None


class C6RecoveryDecider:
    """Determines recovery actions from verification failures (C6 §38-39).

    Usage:
        decider = C6RecoveryDecider()
        context = RecoveryContext(
            verification_result=result,
            policy=policy,
            attempt_number=1,
        )
        decision = decider.decide(context)
        # decision.action == VerificationAction.RESEARCH_MORE
    """

    def __init__(
        self,
        classifier: FailureClassifier | None = None,
    ) -> None:
        self._classifier = classifier or FailureClassifier()

    def decide(
        self,
        context: RecoveryContext,
    ) -> C6RecoveryDecision:
        """Determine the recovery action for a failed verification (C6 §38-39).

        Decision tree:
          1. Check loop bounds (C6 §41)
          2. Classify failures
          3. Determine dominant failure category
          4. Map to recovery action
          5. Check if action is allowed by policy
          6. Return decision

        Args:
            context: Full recovery context including verification result.

        Returns:
            C6RecoveryDecision with action, reason, and constraints.
        """
        result = context.verification_result
        policy = context.policy

        # 1. Check loop bounds (C6 §41)
        if context.attempt_number > policy.thresholds.max_verification_attempts:
            logger.warning(
                "recovery_max_attempts_exceeded",
                execution_id=context.execution_id,
                attempts=context.attempt_number,
                max=policy.thresholds.max_verification_attempts,
            )
            return C6RecoveryDecision(
                action=VerificationAction.HUMAN_REVIEW,
                reason=(
                    f"Maximum verification attempts "
                    f"({policy.thresholds.max_verification_attempts}) exceeded."
                ),
                retry_allowed=False,
                requires_human=True,
                verification_run_id=result.verification_run_id,
            )

        if context.recovery_cycle > policy.thresholds.max_recovery_cycles:
            return C6RecoveryDecision(
                action=VerificationAction.HUMAN_REVIEW,
                reason=(
                    f"Maximum recovery cycles "
                    f"({policy.thresholds.max_recovery_cycles}) exceeded."
                ),
                retry_allowed=False,
                requires_human=True,
                verification_run_id=result.verification_run_id,
            )

        if context.replan_count > policy.thresholds.max_replans:
            return C6RecoveryDecision(
                action=VerificationAction.STOP,
                reason=(
                    f"Maximum replans "
                    f"({policy.thresholds.max_replans}) exceeded."
                ),
                retry_allowed=False,
                requires_human=True,
                verification_run_id=result.verification_run_id,
            )

        # 2. If verification passed, no recovery needed
        if result.status in (
            VerificationStatus.PASSED,
            VerificationStatus.PASSED_WITH_WARNINGS,
        ):
            return C6RecoveryDecision(
                action=VerificationAction.ACCEPT,
                reason="Verification passed.",
                retry_allowed=False,
                requires_human=False,
                verification_run_id=result.verification_run_id,
            )

        # 3. Classify all failed checks
        failed_checks = [
            c for c in result.checks
            if c.status == VerificationStatus.FAILED
        ]

        if not failed_checks:
            # INCONCLUSIVE without specific failures
            return C6RecoveryDecision(
                action=VerificationAction.HUMAN_REVIEW,
                reason="Verification inconclusive with no specific failures.",
                retry_allowed=True,
                requires_human=True,
                verification_run_id=result.verification_run_id,
            )

        classifications = self._classifier.classify_batch(
            [c for c in result.checks]
        )

        # 4. Determine dominant failure category
        category_counts: dict[str, int] = {}
        for fc in classifications:
            cat = fc.category.value
            category_counts[cat] = category_counts.get(cat, 0) + 1

        dominant_category = max(
            category_counts, key=category_counts.get,
        ) if category_counts else IncidentCategory.VERIFICATION.value

        # 5. Check for security/policy failures (always STOP)
        security_failures = [
            fc for fc in classifications
            if fc.category in (
                IncidentCategory.SECURITY,
            )
        ]
        if security_failures:
            return C6RecoveryDecision(
                action=VerificationAction.STOP,
                reason=(
                    f"Security failure detected: "
                    f"{security_failures[0].description}"
                ),
                target_node=context.node_execution_id,
                retry_allowed=False,
                requires_human=True,
                verification_run_id=result.verification_run_id,
            )

        # 6. Map dominant category to action
        action = self._category_to_action(dominant_category)

        # 7. Check if this action was already tried
        action_value = action.value
        if action_value in context.previous_actions:
            # Already tried this action — escalate
            action = self._escalate_action(action)

        # 8. Check policy failure actions
        policy_action = self._check_policy_actions(
            result, policy,
        )
        if policy_action:
            action = policy_action

        # 9. Build decision
        requires_human = action in (
            VerificationAction.HUMAN_REVIEW,
            VerificationAction.STOP,
        )
        retry_allowed = action not in (
            VerificationAction.STOP,
            VerificationAction.HUMAN_REVIEW,
        )

        new_constraints: dict[str, Any] = {}
        if action == VerificationAction.RESEARCH_MORE:
            new_constraints["additional_sources_required"] = True
        elif action == VerificationAction.REGENERATE:
            new_constraints["regenerate_artifact"] = True

        decision = C6RecoveryDecision(
            action=action,
            reason=(
                f"Dominant failure category: {dominant_category}. "
                f"{len(failed_checks)} check(s) failed."
            ),
            target_node=context.node_execution_id,
            new_constraints=new_constraints,
            retry_allowed=retry_allowed,
            requires_human=requires_human,
            verification_run_id=result.verification_run_id,
        )

        logger.info(
            "recovery_decision_made",
            execution_id=context.execution_id,
            action=action.value,
            dominant_category=dominant_category,
            attempt=context.attempt_number,
            cycle=context.recovery_cycle,
        )

        return decision

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _category_to_action(category: str) -> VerificationAction:
        """Map a failure category to a default recovery action."""
        mapping = {
            IncidentCategory.PROVIDER.value: VerificationAction.RETRY,
            IncidentCategory.TOOL.value: VerificationAction.RETRY,
            IncidentCategory.AGENT.value: VerificationAction.REASSIGN,
            IncidentCategory.ORCHESTRATION.value: VerificationAction.REPLAN,
            IncidentCategory.STATE.value: VerificationAction.ROLLBACK,
            IncidentCategory.MEMORY.value: VerificationAction.RETRY,
            IncidentCategory.CONTEXT.value: VerificationAction.RETRY,
            IncidentCategory.EVIDENCE.value: VerificationAction.RESEARCH_MORE,
            IncidentCategory.ARTIFACT.value: VerificationAction.REGENERATE,
            IncidentCategory.VERIFICATION.value: VerificationAction.RETRY,
            IncidentCategory.SECURITY.value: VerificationAction.STOP,
            IncidentCategory.POLICY.value: VerificationAction.HUMAN_REVIEW,
            IncidentCategory.WORLD.value: VerificationAction.RETRY,
        }
        return mapping.get(category, VerificationAction.HUMAN_REVIEW)

    @staticmethod
    def _escalate_action(
        current: VerificationAction,
    ) -> VerificationAction:
        """Escalate to a stronger recovery action when the current one failed."""
        escalation = {
            VerificationAction.RETRY: VerificationAction.REASSIGN,
            VerificationAction.REASSIGN: VerificationAction.REPLAN,
            VerificationAction.RESEARCH_MORE: VerificationAction.HUMAN_REVIEW,
            VerificationAction.REGENERATE: VerificationAction.HUMAN_REVIEW,
            VerificationAction.ROLLBACK: VerificationAction.REPLAN,
            VerificationAction.REPLAN: VerificationAction.HUMAN_REVIEW,
            VerificationAction.HUMAN_REVIEW: VerificationAction.STOP,
            VerificationAction.STOP: VerificationAction.STOP,
            VerificationAction.ACCEPT: VerificationAction.ACCEPT,
        }
        return escalation.get(current, VerificationAction.HUMAN_REVIEW)

    @staticmethod
    def _check_policy_actions(
        result: C6VerificationResult,
        policy: VerificationPolicy,
    ) -> VerificationAction | None:
        """Check if the policy specifies a specific action for a failure."""
        if not policy.failure_actions:
            return None

        for failure in result.failures:
            for keyword, fa in policy.failure_actions.items():
                if keyword.lower() in failure.lower():
                    try:
                        return VerificationAction(fa.action)
                    except ValueError:
                        continue

        return None