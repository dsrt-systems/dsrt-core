"""
Failure Analyzer (C8 §45-46).

Classifies and analyzes Arena run failures to answer:
  - Where did it fail?
  - Why did it fail?
  - What was the agent doing?
  - Which model/tool was involved?
  - Did recovery succeed?
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from schemas.domain.enums import FailureCategory

from core.observability.logging import get_logger


logger = get_logger("dsrt.arena.analyzer")


@dataclass
class FailureAnalysis:
    """Detailed analysis of a single failure (C8 §46)."""
    run_id: str
    category: FailureCategory
    description: str
    location: str = ""
    agent_action: str = ""
    model_version: str | None = None
    tool_slug: str | None = None
    world_state: str | None = None
    recovery_attempted: bool = False
    recovery_succeeded: bool = False
    root_cause_candidates: list[str] = field(default_factory=list)
    trajectory_evidence: list[str] = field(default_factory=list)


class FailureAnalyzer:
    """Analyzes Arena run failures (C8 §45-46).

    Usage:
        analyzer = FailureAnalyzer()
        analysis = analyzer.analyze_run(
            run_id="arn_1",
            trajectory_events=events,
            performance_profile=profile,
        )
    """

    def analyze_run(
        self,
        *,
        run_id: str,
        trajectory_events: list[dict[str, Any]],
        performance_profile: dict[str, Any] | None = None,
    ) -> list[FailureAnalysis]:
        """Analyze all failures in an Arena run.

        Args:
            run_id: The Arena run ID.
            trajectory_events: List of trajectory event dicts.
            performance_profile: Optional profile data.

        Returns:
            List of FailureAnalysis, one per detected failure.
        """
        failures: list[FailureAnalysis] = []

        # Find failure events in the trajectory
        failure_events = [
            e for e in trajectory_events
            if "FAILED" in e.get("event_type", "")
            or "ERROR" in e.get("event_type", "")
        ]

        for event in failure_events:
            analysis = self._analyze_event(run_id, event, trajectory_events)
            failures.append(analysis)

        # If no explicit failures but the run didn't complete
        if not failures and performance_profile:
            if not performance_profile.get("task_success", False):
                failures.append(FailureAnalysis(
                    run_id=run_id,
                    category=FailureCategory.TASK_FAILURE,
                    description="Task did not complete successfully.",
                    root_cause_candidates=["timeout", "resource_exhaustion", "agent_error"],
                ))

        logger.info(
            "failure_analysis_complete",
            run_id=run_id,
            failures_detected=len(failures),
            categories=[f.category.value for f in failures],
        )

        return failures

    def _analyze_event(
        self,
        run_id: str,
        event: dict[str, Any],
        all_events: list[dict[str, Any]],
    ) -> FailureAnalysis:
        """Analyze a single failure event in context."""
        event_type = event.get("event_type", "")
        payload = event.get("payload", {})

        # Classify the failure
        category = self._classify_failure(event_type, payload)

        # Find context: what was happening before the failure?
        seq = event.get("sequence", 0)
        preceding = [
            e for e in all_events
            if e.get("sequence", 0) < seq
        ]
        last_action = preceding[-1] if preceding else {}

        # Check for recovery attempts after this failure
        following = [
            e for e in all_events
            if e.get("sequence", 0) > seq
        ]
        recovery_events = [
            e for e in following
            if "RETRY" in e.get("event_type", "")
            or "RECOVERY" in e.get("event_type", "")
            or "REASSIGN" in e.get("event_type", "")
        ]
        recovery_success = any(
            "COMPLETED" in e.get("event_type", "")
            for e in following
            if e.get("sequence", 0) > seq
        )

        # Build root cause candidates
        root_causes = self._suggest_root_causes(category, payload)

        return FailureAnalysis(
            run_id=run_id,
            category=category,
            description=payload.get("error", event_type),
            location=f"sequence={seq}",
            agent_action=last_action.get("event_type", "unknown"),
            model_version=event.get("model_version"),
            tool_slug=event.get("tool_slug") or payload.get("tool_slug"),
            recovery_attempted=len(recovery_events) > 0,
            recovery_succeeded=recovery_success,
            root_cause_candidates=root_causes,
            trajectory_evidence=[
                f"seq={e.get('sequence')}: {e.get('event_type')}"
                for e in all_events
                if abs(e.get("sequence", 0) - seq) <= 3
            ],
        )

    @staticmethod
    def _classify_failure(
        event_type: str, payload: dict[str, Any],
    ) -> FailureCategory:
        """Classify a failure event into the taxonomy (C8 §45)."""
        et = event_type.upper()

        if "MODEL" in et:
            return FailureCategory.MODEL_FAILURE
        if "TOOL" in et:
            return FailureCategory.TOOL_FAILURE
        if "AGENT" in et:
            return FailureCategory.AGENT_FAILURE
        if "WORLD" in et:
            return FailureCategory.WORLD_FAILURE
        if "VERIFICATION" in et:
            return FailureCategory.VERIFICATION_FAILURE
        if "CONTEXT" in et or "MEMORY" in et:
            return FailureCategory.CONTEXT_FAILURE
        if "SECURITY" in et or "PERMISSION" in et:
            return FailureCategory.SECURITY_FAILURE
        if "RESOURCE" in et or "LIMIT" in et:
            return FailureCategory.RESOURCE_FAILURE
        if "TIMEOUT" in et:
            return FailureCategory.TIMEOUT
        if "PLAN" in et or "NODE" in et:
            return FailureCategory.PLANNING_FAILURE

        error_code = str(payload.get("error_code", ""))
        if "PROVIDER" in error_code:
            return FailureCategory.MODEL_FAILURE
        if "CREDENTIAL" in error_code:
            return FailureCategory.SECURITY_FAILURE

        return FailureCategory.TASK_FAILURE

    @staticmethod
    def _suggest_root_causes(
        category: FailureCategory, payload: dict[str, Any],
    ) -> list[str]:
        """Suggest possible root causes based on failure category."""
        causes: list[str] = []

        if category == FailureCategory.MODEL_FAILURE:
            causes = ["provider_timeout", "rate_limit", "model_unavailable", "context_too_large"]
        elif category == FailureCategory.TOOL_FAILURE:
            causes = ["tool_timeout", "network_error", "invalid_arguments", "permission_denied"]
        elif category == FailureCategory.AGENT_FAILURE:
            causes = ["agent_error", "initialization_failed", "execution_timeout"]
        elif category == FailureCategory.WORLD_FAILURE:
            causes = ["world_unavailable", "resource_exhausted", "component_crash"]
        elif category == FailureCategory.RESOURCE_FAILURE:
            causes = ["budget_exceeded", "token_limit", "duration_limit"]
        elif category == FailureCategory.TIMEOUT:
            causes = ["execution_timeout", "model_timeout", "tool_timeout"]
        elif category == FailureCategory.SECURITY_FAILURE:
            causes = ["permission_denied", "credential_invalid", "policy_violation"]
        else:
            causes = ["unknown_error", "configuration_issue"]

        # Refine based on payload
        error_msg = str(payload.get("error", "")).lower()
        if "timeout" in error_msg:
            causes.insert(0, "timeout")
        if "rate" in error_msg and "limit" in error_msg:
            causes.insert(0, "rate_limited")
        if "memory" in error_msg or "oom" in error_msg:
            causes.insert(0, "out_of_memory")

        return causes[:5]  # Top 5 candidates