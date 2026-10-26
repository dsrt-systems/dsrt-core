"""
C11.6 — Trigger Detector.

Classifies incoming C10 telemetry events into actionable AdaptationTriggerType signals.
"""

from __future__ import annotations

import logging
from typing import Any

from schemas.domain.adaptive_execution import (
    AdaptationTriggerType,
    ExecutionEvent,
)
from schemas.domain.economic_optimization import OptimizationPlanOutput

logger = logging.getLogger(__name__)


class TriggerDetector:
    """Detects adaptation triggers from execution telemetry and budget bounds."""

    def detect_trigger(
        self,
        event: ExecutionEvent,
        plan: OptimizationPlanOutput,
    ) -> AdaptationTriggerType | None:
        """
        Analyze an ExecutionEvent against plan constraints and budget limits.
        Returns the primary trigger type or None if execution is progressing normally.
        """
        limits = plan.budget_limits
        budget = limits.total_authorized_cost if limits else (plan.authorized_budget or 0.0)

        # 1. Budget Exhaustion
        if budget > 0 and event.current_cost >= budget:
            logger.warning(
                "Execution %s exhausted budget: $%.4f >= $%.4f",
                event.execution_id, event.current_cost, budget
            )
            return AdaptationTriggerType.BUDGET_EXHAUSTED

        # 2. Budget Warning (85% consumed)
        if budget > 0 and event.current_cost >= (0.85 * budget):
            logger.info(
                "Execution %s budget warning: $%.4f >= 85%% of $%.4f",
                event.execution_id, event.current_cost, budget
            )
            return AdaptationTriggerType.BUDGET_WARNING

        # 3. Latency Overrun
        if plan.constraints.max_latency_ms is not None:
            if event.current_latency_ms > plan.constraints.max_latency_ms:
                return AdaptationTriggerType.LATENCY_OVERRUN

        # 4. Explicit Event Type Classification
        e_type = event.event_type.lower()
        err_msg = (event.error_message or "").lower()
        details = event.details or {}

        if "schema" in err_msg or "json" in err_msg or "invalid_output" in e_type:
            return AdaptationTriggerType.MODEL_OUTPUT_INVALID

        if "context" in err_msg or "token_limit" in err_msg or "context_length" in e_type:
            return AdaptationTriggerType.CONTEXT_LIMIT_EXCEEDED

        if "tool_not_found" in err_msg or "tool_unavailable" in e_type:
            return AdaptationTriggerType.TOOL_UNAVAILABLE

        if "tool" in e_type or "tool_error" in err_msg:
            return AdaptationTriggerType.TOOL_EXECUTION_ERROR

        if "test" in e_type or "test_failed" in err_msg or details.get("tests_failed"):
            return AdaptationTriggerType.TEST_FAILURE

        if "retrieval" in e_type or "no_evidence" in err_msg:
            return AdaptationTriggerType.RETRIEVAL_INSUFFICIENT

        if "verification" in e_type or "check_failed" in err_msg:
            return AdaptationTriggerType.VERIFICATION_FAILURE

        if event.attempt_number > 2 or "repeated_failure" in e_type:
            return AdaptationTriggerType.MODEL_REPEATED_FAILURE

        if "error" in e_type or event.error_message:
            return AdaptationTriggerType.MODEL_OUTPUT_INVALID

        return None