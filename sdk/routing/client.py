# sdk/routing/client.py
"""
C9 Routing SDK (§53–54).

Agent-facing API for route resolution.  Agents request routes by
describing their *requirements*, not by naming specific providers.

Usage:
    sdk = RoutingSDK(router, evidence_aggregator, event_emitter)
    route = sdk.resolve(requirements)
    stage_route = sdk.resolve_stage(requirements, stage="verification")

Core remains authoritative — agents cannot inject arbitrary models
or bypass organization policies (§54).
"""

from __future__ import annotations

from typing import Any

from core.routing.contracts import (
    AggregatedEvidence,
    Route,
    RouteCandidate,
    RouteDecision,
    RoutingPolicy,
    RoutingProfile,
    TaskRequirements,
)
from core.routing.enums import (
    ExecutionStage,
    RoutingStatus,
)
from core.routing.events import RoutingEventEmitter, RoutingEventType
from core.routing.selector.router import IntelligenceRouter


class RoutingSDK:
    """Agent-facing routing API (§53–54).

    This is the boundary between agents and the Core routing engine.
    Agents describe *what they need*; the Core decides *how to provide it*.

    Args:
        router: The IntelligenceRouter instance.
        event_emitter: Event emitter for routing telemetry.
        default_policy: Default routing policy if none specified.
        default_profile: Default routing profile if none specified.
    """

    def __init__(
        self,
        router: IntelligenceRouter,
        event_emitter: RoutingEventEmitter | None = None,
        default_policy: RoutingPolicy | None = None,
        default_profile: RoutingProfile | None = None,
    ) -> None:
        self._router = router
        self._emitter = event_emitter or RoutingEventEmitter()
        self._default_policy = default_policy
        self._default_profile = default_profile

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        requirements: TaskRequirements,
        candidates: list[RouteCandidate],
        evidence_map: dict[str, AggregatedEvidence] | None = None,
        policy: RoutingPolicy | None = None,
        profile: RoutingProfile | None = None,
    ) -> RouteDecision:
        """Resolve a route for a task (§53).

        This is the primary entry point.  The agent provides
        requirements and pre-generated candidates; the SDK runs
        the full routing pipeline.

        Args:
            requirements: Structured task requirements.
            candidates: Pre-generated, policy-filtered candidates.
            evidence_map: Evidence per candidate.
            policy: Routing policy override.
            profile: Routing profile override.

        Returns:
            Complete ``RouteDecision`` with selected route.

        Raises:
            ValueError: If requirements are invalid.
        """
        if not requirements.task_id:
            raise ValueError("requirements.task_id must be non-empty")

        pol = policy or self._default_policy
        prof = profile or self._default_profile
        task_id = requirements.task_id

        self._emitter.routing_started(task_id)
        self._emitter.requirements_extracted(
            task_id,
            domain=requirements.classification.primary_domain.value,
            capabilities=len(requirements.capabilities),
        )
        self._emitter.candidates_generated(
            task_id, "pending", count=len(candidates),
        )

        # Emit rejections
        for c in candidates:
            if not c.is_eligible and c.rejections:
                self._emitter.candidate_rejected(
                    task_id, "pending",
                    candidate_id=c.candidate_id,
                    reason=c.rejections[0].detail,
                )

        # Run the router
        decision = self._router.route(
            requirements=requirements,
            candidates=candidates,
            policy=pol,
            profile=prof,
            evidence_map=evidence_map,
        )

        # Emit result events
        if decision.status == RoutingStatus.SELECTED:
            route = decision.selected_route
            self._emitter.route_selected(
                task_id, decision.decision_id,
                model_id=route.model_id if route else "unknown",
                agent_id=route.agent_id if route else "unknown",
            )
            self._emitter.routing_completed(task_id, decision.decision_id)
        else:
            self._emitter.routing_failed(
                task_id, decision.decision_id,
                reason=decision.decision_reason.get("reason", "unknown"),
            )

        return decision

    def resolve_stage(
        self,
        requirements: TaskRequirements,
        candidates: list[RouteCandidate],
        stage: ExecutionStage,
        evidence_map: dict[str, AggregatedEvidence] | None = None,
        policy: RoutingPolicy | None = None,
        profile: RoutingProfile | None = None,
    ) -> RouteDecision:
        """Resolve a route for a specific execution stage (§53).

        Used for intra-task model routing (§32) when different
        stages need different model profiles.

        Args:
            requirements: Task requirements.
            candidates: Stage-eligible candidates.
            stage: The execution stage being routed.
            evidence_map: Evidence per candidate.
            policy: Routing policy override.
            profile: Routing profile override.

        Returns:
            ``RouteDecision`` for the specific stage.
        """
        self._emitter.emit(
            RoutingEventType.ROUTE_EVALUATED,
            requirements.task_id,
            stage=stage.value,
        )
        return self.resolve(
            requirements=requirements,
            candidates=candidates,
            evidence_map=evidence_map,
            policy=policy,
            profile=profile,
        )

    # ------------------------------------------------------------------
    # Boundary enforcement (§54)
    # ------------------------------------------------------------------

    def validate_agent_request(
        self,
        requirements: TaskRequirements,
        policy: RoutingPolicy | None = None,
    ) -> list[str]:
        """Validate that an agent's request respects boundaries (§54).

        Agents can request capabilities but cannot demand specific
        providers unless policy explicitly permits it.

        Returns:
            List of validation error messages (empty = valid).
        """
        errors: list[str] = []

        # Check if agent is trying to specify a model directly
        metadata = requirements.metadata or {}
        if "forced_model" in metadata:
            pol = policy or self._default_policy
            if pol and not pol.constraints.allowed_models:
                errors.append(
                    "Agent cannot force a specific model without "
                    "explicit policy permission"
                )

        if "forced_provider" in metadata:
            pol = policy or self._default_policy
            if pol and not pol.constraints.allowed_providers:
                errors.append(
                    "Agent cannot force a specific provider without "
                    "explicit policy permission"
                )

        return errors

    @property
    def events(self) -> RoutingEventEmitter:
        """Access the event emitter for inspection."""
        return self._emitter