"""C9.10 - Orchestration Routing Hook.

Provides C6 orchestration with C9 routing recommendations.
"""
from __future__ import annotations

import uuid
from typing import Any

from core.routing.contracts import (
    AggregatedEvidence,
    QualityRequirements,
    RouteCandidate,
    RouteDecision,
    RoutingPolicy,
    RoutingProfile,
    TaskRequirements,
)
from core.routing.enums import ExecutionStage, QualityLevel
from core.routing.requirements.extractor import RequirementExtractor
from core.routing.selector.router import IntelligenceRouter


_STAGE_QUALITY: dict[ExecutionStage, QualityLevel] = {
    ExecutionStage.PLANNING: QualityLevel.STANDARD,
    ExecutionStage.RETRIEVAL: QualityLevel.STANDARD,
    ExecutionStage.ANALYSIS: QualityLevel.HIGH,
    ExecutionStage.SYNTHESIS: QualityLevel.HIGH,
    ExecutionStage.VERIFICATION: QualityLevel.STRICT,
    ExecutionStage.FINALIZATION: QualityLevel.STANDARD,
}


class OrchestrationRoutingHook:
    """Hook for C6 orchestration to consult C9 routing."""

    def __init__(
        self,
        router: IntelligenceRouter,
        extractor: RequirementExtractor | None = None,
    ) -> None:
        self._router = router
        self._extractor = extractor or RequirementExtractor()

    def get_route_for_task(
        self,
        task_description: str,
        candidates: list[RouteCandidate],
        task_id: str | None = None,
        policy: RoutingPolicy | None = None,
        profile: RoutingProfile | None = None,
        evidence_map: dict[str, AggregatedEvidence] | None = None,
        hints: dict[str, Any] | None = None,
    ) -> RouteDecision:
        task_id = task_id or f"task_{uuid.uuid4().hex[:12]}"
        requirements = self._extractor.extract(
            task_id=task_id,
            description=task_description,
            hints=hints,
        )
        return self._router.route(
            requirements=requirements,
            candidates=candidates,
            policy=policy,
            profile=profile,
            evidence_map=evidence_map,
        )

    def get_stage_route(
        self,
        stage: ExecutionStage,
        parent_decision: RouteDecision,
        candidates: list[RouteCandidate],
        policy: RoutingPolicy | None = None,
    ) -> RouteDecision:
        parent_reqs = parent_decision.requirements
        if parent_reqs is None:
            raise ValueError("Parent decision has no requirements")

        stage_quality = _STAGE_QUALITY.get(stage, parent_reqs.quality.overall)
        stage_reqs = TaskRequirements(
            task_id=f"{parent_reqs.task_id}_{stage.value.lower()}",
            description=f"[{stage.value}] {parent_reqs.description}",
            classification=parent_reqs.classification,
            capabilities=parent_reqs.capabilities,
            quality=QualityRequirements(overall=stage_quality),
            resources=parent_reqs.resources,
            security=parent_reqs.security,
            preferred_tools=parent_reqs.preferred_tools,
            required_tools=parent_reqs.required_tools,
            output_type=parent_reqs.output_type,
            metadata={
                **parent_reqs.metadata,
                "stage": stage.value,
                "parent_task_id": parent_reqs.task_id,
            },
        )
        return self._router.route(
            requirements=stage_reqs,
            candidates=candidates,
            policy=policy,
        )

    def should_replan(
        self,
        current_decision: RouteDecision,
        execution_feedback: dict[str, Any],
    ) -> bool:
        if execution_feedback.get("status") == "FAILED":
            return True
        reqs = current_decision.requirements
        if reqs is None:
            return False
        quality_score = execution_feedback.get("quality_score")
        if quality_score is not None:
            thresholds = {
                QualityLevel.STRICT: 0.95,
                QualityLevel.HIGH: 0.85,
                QualityLevel.STANDARD: 0.7,
                QualityLevel.MINIMUM: 0.5,
            }
            if quality_score < thresholds.get(reqs.quality.overall, 0.7):
                return True
        cost = execution_feedback.get("cost_usd")
        if cost is not None and reqs.resources.max_cost_usd is not None:
            if cost > reqs.resources.max_cost_usd * 2:
                return True
        duration = execution_feedback.get("duration_seconds")
        if duration is not None and reqs.resources.max_duration_seconds is not None:
            if duration > reqs.resources.max_duration_seconds * 1.5:
                return True
        return False
