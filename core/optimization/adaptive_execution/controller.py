"""
C11.6 — Adaptive Execution Controller (top-level coordinator).

Subscribes to execution telemetry, maintains attempt history, runs trigger detection,
evaluates recovery policies, and emits bounded AdaptationDecisions.
"""

from __future__ import annotations

import logging
from typing import Any

from schemas.domain.adaptive_execution import (
    AdaptationDecision,
    AdaptationRecord,
    ExecutionEvent,
)
from schemas.domain.economic_optimization import OptimizationPlanOutput

from core.optimization.adaptive_execution.recovery import RecoveryPolicyEngine
from core.optimization.adaptive_execution.triggers import TriggerDetector

logger = logging.getLogger(__name__)


class AdaptiveExecutionController:
    """
    Monitors execution events, tracks adaptation attempts per execution,
    and returns bounded adaptation directives.
    """

    def __init__(
        self,
        trigger_detector: TriggerDetector | None = None,
        recovery_engine: RecoveryPolicyEngine | None = None,
    ) -> None:
        self._detector = trigger_detector or TriggerDetector()
        self._recovery_engine = recovery_engine or RecoveryPolicyEngine()
        # In-memory history tracking: execution_id -> trigger_type -> count
        self._attempt_history: dict[str, dict[str, int]] = {}

    def observe_and_adapt(
        self,
        event: ExecutionEvent,
        plan: OptimizationPlanOutput,
        escalation_model_fingerprint: str | None = None,
    ) -> AdaptationDecision | None:
        """
        Process a C10 execution event.
        Returns an AdaptationDecision if adaptation is required, or None if execution is healthy.
        """
        trigger = self._detector.detect_trigger(event, plan)
        if trigger is None:
            logger.debug("Execution %s is healthy. No adaptation required.", event.execution_id)
            return None

        # Track attempt history
        exec_id = event.execution_id
        if exec_id not in self._attempt_history:
            self._attempt_history[exec_id] = {}

        t_key = trigger.value
        current_count = self._attempt_history[exec_id].get(t_key, 0)

        decision = self._recovery_engine.evaluate_recovery(
            trigger=trigger,
            event=event,
            plan=plan,
            attempt_history=self._attempt_history[exec_id],
            escalation_model_fingerprint=escalation_model_fingerprint,
        )

        # Update counter
        self._attempt_history[exec_id][t_key] = current_count + 1

        logger.info(
            "Adaptation decision for exec=%s trigger=%s action=%s attempt=%d",
            exec_id, trigger.value, decision.recommended_action.value, decision.current_attempt
        )
        return decision

    def clear_history(self, execution_id: str) -> None:
        """Clear history after execution finishes."""
        self._attempt_history.pop(execution_id, None)