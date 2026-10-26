"""
C11.6 — Recovery Policy Engine.

Maps detected triggers to bounded adaptation actions and calculates costs,
attempt bounds, and required user permissions.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from schemas.domain.adaptive_execution import (
    AdaptationActionType,
    AdaptationDecision,
    AdaptationTriggerType,
    ExecutionEvent,
)
from schemas.domain.economic_optimization import OptimizationPlanOutput

logger = logging.getLogger(__name__)


class RecoveryPolicyEngine:
    """Evaluates triggers and constructs bounded adaptation decisions."""

    def evaluate_recovery(
        self,
        trigger: AdaptationTriggerType,
        event: ExecutionEvent,
        plan: OptimizationPlanOutput,
        attempt_history: dict[str, int],
        escalation_model_fingerprint: str | None = None,
    ) -> AdaptationDecision:
        decision_id = str(uuid.uuid4())
        attempts_so_far = attempt_history.get(trigger.value, 0) + 1
        max_allowed_retries = plan.budget_limits.max_retries if plan.budget_limits else 3

        # Default cost per adaptation step
        base_step_cost = 0.005

        # Rule 1: Budget Exhausted -> Stop Execution
        if trigger == AdaptationTriggerType.BUDGET_EXHAUSTED:
            return AdaptationDecision(
                decision_id=decision_id,
                execution_id=event.execution_id,
                trigger_type=trigger,
                recommended_action=AdaptationActionType.STOP_EXECUTION,
                max_attempts=1,
                current_attempt=attempts_so_far,
                estimated_adaptation_cost=0.0,
                reason="Authorized budget cap reached. Stopping execution to prevent overrun.",
                requires_user_approval=False,
                is_bounded=True,
            )

        # Rule 2: Budget Warning -> Reduce optional operations
        if trigger == AdaptationTriggerType.BUDGET_WARNING:
            return AdaptationDecision(
                decision_id=decision_id,
                execution_id=event.execution_id,
                trigger_type=trigger,
                recommended_action=AdaptationActionType.REDUCE_OPTIONAL_OPS,
                max_attempts=1,
                current_attempt=attempts_so_far,
                estimated_adaptation_cost=0.0,
                reason="Budget 85% consumed. Pruning optional verification and secondary tool steps.",
                requires_user_approval=False,
                is_bounded=True,
            )

        # Rule 3: Latency Overrun -> Recommend faster config
        if trigger == AdaptationTriggerType.LATENCY_OVERRUN:
            return AdaptationDecision(
                decision_id=decision_id,
                execution_id=event.execution_id,
                trigger_type=trigger,
                recommended_action=AdaptationActionType.RECOMMEND_FASTER_CONFIG,
                max_attempts=1,
                current_attempt=attempts_so_far,
                estimated_adaptation_cost=0.0,
                reason="Latency threshold exceeded. Recommending higher-throughput candidate.",
                requires_user_approval=False,
                is_bounded=True,
            )

        # Rule 4: Exceeded attempt bounds for active trigger -> Escalate or Stop
        if attempts_so_far > max_allowed_retries:
            if escalation_model_fingerprint and trigger == AdaptationTriggerType.MODEL_REPEATED_FAILURE:
                return AdaptationDecision(
                    decision_id=decision_id,
                    execution_id=event.execution_id,
                    trigger_type=trigger,
                    recommended_action=AdaptationActionType.MODEL_ESCALATION,
                    target_model_fingerprint=escalation_model_fingerprint,
                    max_attempts=1,
                    current_attempt=attempts_so_far,
                    estimated_adaptation_cost=base_step_cost * 3.0,
                    reason=f"Max retries ({max_allowed_retries}) exhausted on primary model. Escalating to model {escalation_model_fingerprint}.",
                    requires_user_approval=True,
                    is_bounded=True,
                )
            return AdaptationDecision(
                decision_id=decision_id,
                execution_id=event.execution_id,
                trigger_type=trigger,
                recommended_action=AdaptationActionType.STOP_EXECUTION,
                max_attempts=max_allowed_retries,
                current_attempt=attempts_so_far,
                estimated_adaptation_cost=0.0,
                reason=f"Exceeded maximum recovery attempts ({max_allowed_retries}) for trigger {trigger.value}.",
                requires_user_approval=False,
                is_bounded=True,
            )

        # Rule 5: Specific Recovery Actions
        if trigger == AdaptationTriggerType.MODEL_OUTPUT_INVALID:
            return AdaptationDecision(
                decision_id=decision_id,
                execution_id=event.execution_id,
                trigger_type=trigger,
                recommended_action=AdaptationActionType.RETRY_CONSTRAINED,
                max_attempts=max_allowed_retries,
                current_attempt=attempts_so_far,
                estimated_adaptation_cost=base_step_cost,
                reason="Model output schema validation failed. Retrying with strict output constraints.",
                requires_user_approval=False,
                is_bounded=True,
            )

        if trigger == AdaptationTriggerType.CONTEXT_LIMIT_EXCEEDED:
            return AdaptationDecision(
                decision_id=decision_id,
                execution_id=event.execution_id,
                trigger_type=trigger,
                recommended_action=AdaptationActionType.RECOMPILE_CONTEXT,
                max_attempts=max_allowed_retries,
                current_attempt=attempts_so_far,
                estimated_adaptation_cost=base_step_cost * 0.5,
                reason="Model context window exceeded. Recompiling and pruning lower-relevance context.",
                requires_user_approval=False,
                is_bounded=True,
            )

        if trigger == AdaptationTriggerType.TEST_FAILURE:
            return AdaptationDecision(
                decision_id=decision_id,
                execution_id=event.execution_id,
                trigger_type=trigger,
                recommended_action=AdaptationActionType.BOUNDED_REPAIR,
                max_attempts=max_allowed_retries,
                current_attempt=attempts_so_far,
                estimated_adaptation_cost=base_step_cost * 2.0,
                reason="Code execution tests failed. Initiating targeted repair cycle with error stack trace.",
                requires_user_approval=False,
                is_bounded=True,
            )

        if trigger == AdaptationTriggerType.TOOL_UNAVAILABLE:
            fallback = event.details.get("fallback_tool", "shell")
            return AdaptationDecision(
                decision_id=decision_id,
                execution_id=event.execution_id,
                trigger_type=trigger,
                recommended_action=AdaptationActionType.TOOL_FALLBACK,
                target_tool=fallback,
                max_attempts=max_allowed_retries,
                current_attempt=attempts_so_far,
                estimated_adaptation_cost=base_step_cost,
                reason=f"Requested tool is unavailable. Switching to fallback tool '{fallback}'.",
                requires_user_approval=False,
                is_bounded=True,
            )

        if trigger == AdaptationTriggerType.RETRIEVAL_INSUFFICIENT:
            return AdaptationDecision(
                decision_id=decision_id,
                execution_id=event.execution_id,
                trigger_type=trigger,
                recommended_action=AdaptationActionType.TARGETED_RETRIEVAL,
                max_attempts=max_allowed_retries,
                current_attempt=attempts_so_far,
                estimated_adaptation_cost=base_step_cost,
                reason="Retrieval results returned insufficient evidence. Performing targeted query expansion.",
                requires_user_approval=False,
                is_bounded=True,
            )

        # Generic Fallback
        return AdaptationDecision(
            decision_id=decision_id,
            execution_id=event.execution_id,
            trigger_type=trigger,
            recommended_action=AdaptationActionType.RETRY_CONSTRAINED,
            max_attempts=max_allowed_retries,
            current_attempt=attempts_so_far,
            estimated_adaptation_cost=base_step_cost,
            reason=f"Generic error detected ({trigger.value}). Issuing bounded retry.",
            requires_user_approval=False,
            is_bounded=True,
        )