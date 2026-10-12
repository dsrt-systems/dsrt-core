"""
Tool Router — The Central Resolution Service (C3 §10).

Chains the Tool Registry (C3.3) and Tool Permission Engine (C3.4) into
a single, deterministic resolution flow:

    capability request
        ↓
    [1] Registry lookup       → candidate ToolVersions
        ↓
    [2] Version filtering      → eligible candidates
        ↓
    [3] Permission enforcement → authorized candidate
        ↓
    [4] Environment resolution → final route
        ↓
    [5] Audit decision persisted
        ↓
    ResolvedToolRoute → ExecutionEngine
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from schemas.domain.agent import AgentManifest
from schemas.domain.task import TaskConstraints
from schemas.domain.tool import ToolManifest, ToolVersion

from core.api.errors.exceptions import NotFoundError
from core.observability.logging import get_logger
from core.security.context import SecurityContext
from core.storage.identifiers import IdPrefix, new_id
from core.tools.errors import (
    ToolApprovalRequiredError,
    ToolNotFoundError,
    ToolPermissionDeniedError,
    ToolVersionUnavailableError,
)
from core.tools.permissions.decision import ToolPermissionDecision
from core.tools.permissions.engine import ToolPermissionEngine
from core.tools.registry.registry import ToolRegistry
from core.tools.router.decision import (
    ResolvedToolRoute,
    ToolRouteCandidate,
    ToolRouteRejection,
    ToolRouteRejectionReason,
    ToolRouteStatus,
    ToolRoutingDecision,
)


logger = get_logger("dsrt.tools.router")

_SUPPORTED_CONTRACT_VERSIONS = {"1.0"}


class ToolRouter:
    """Deterministic Tool Router — resolves capability requests to execution-ready routes."""

    def __init__(
        self,
        registry: ToolRegistry,
        permission_engine: ToolPermissionEngine,
    ) -> None:
        self._registry = registry
        self._permissions = permission_engine

    async def route(
        self,
        *,
        tool_slug: str,
        agent_manifest: AgentManifest,
        requested_version: str | None = None,
        organization_id: str | None = None,
        security_context: SecurityContext | None = None,
        task_constraints: TaskConstraints | None = None,
        current_tool_calls: int = 0,
        environment_id: str | None = None,
        request_id: str | None = None,
    ) -> ResolvedToolRoute:
        """Resolve a tool capability request to an execution-ready route.

        Raises:
            ToolNotFoundError: if the tool slug is not registered
            ToolVersionUnavailableError: if the requested version is not registered
            ToolPermissionDeniedError: if authorization fails
            ToolApprovalRequiredError: if human approval is required
        """
        start_time = time.perf_counter()
        req_id = request_id or new_id(IdPrefix.REQUEST)

        # -------------------------------------------------------------------
        # 1. Registry lookup — resolve tool_slug to ToolVersion
        # -------------------------------------------------------------------
        try:
            tool_version = await self._registry.resolve_tool_version(
                slug=tool_slug,
                version=requested_version,
                organization_id=organization_id,
            )
        except ToolNotFoundError:
            decision = self._build_not_found_decision(
                req_id, tool_slug, requested_version, start_time, environment_id,
            )
            logger.warning(
                "tool_routing_tool_not_found",
                tool_slug=tool_slug,
                requested_version=requested_version,
            )
            raise ToolNotFoundError(
                f"Tool '{tool_slug}' not found in registry.",
                metadata={"routing_decision": decision.model_dump(mode="json")},
            )
        except ToolVersionUnavailableError:
            decision = self._build_version_unavailable_decision(
                req_id, tool_slug, requested_version, start_time, environment_id,
            )
            logger.warning(
                "tool_routing_version_unavailable",
                tool_slug=tool_slug,
                requested_version=requested_version,
            )
            raise ToolVersionUnavailableError(
                f"Version '{requested_version}' of tool '{tool_slug}' not available.",
                metadata={"routing_decision": decision.model_dump(mode="json")},
            )

        # -------------------------------------------------------------------
        # 2. Build candidate record & gather all candidates for audit
        # -------------------------------------------------------------------
        selected_candidate = self._to_candidate(tool_version)
        all_candidates = await self._gather_candidates_for_audit(
            tool_slug=tool_slug, organization_id=organization_id,
        )
        rejections: list[ToolRouteRejection] = []

        # Record rejections of all other candidates (not selected)
        for cand in all_candidates:
            if cand.tool_version_id != selected_candidate.tool_version_id:
                reason, detail = self._classify_rejection(
                    cand, selected_candidate, requested_version,
                )
                rejections.append(
                    ToolRouteRejection(candidate=cand, reason=reason, detail=detail),
                )

        # -------------------------------------------------------------------
        # 3. Contract version compatibility check
        # -------------------------------------------------------------------
        if tool_version.contract_version not in _SUPPORTED_CONTRACT_VERSIONS:
            rejections.append(
                ToolRouteRejection(
                    candidate=selected_candidate,
                    reason=ToolRouteRejectionReason.CONTRACT_VERSION_INCOMPATIBLE,
                    detail=(
                        f"Tool contract version '{tool_version.contract_version}' "
                        f"is not in supported set {_SUPPORTED_CONTRACT_VERSIONS}."
                    ),
                ),
            )
            decision = ToolRoutingDecision(
                request_id=req_id,
                tool_slug=tool_slug,
                requested_version=requested_version,
                status=ToolRouteStatus.VERSION_UNAVAILABLE,
                selected_candidate=None,
                candidates_considered=all_candidates,
                rejections=rejections,
                decided_at=datetime.now(timezone.utc),
                decision_latency_ms=int((time.perf_counter() - start_time) * 1000),
                environment_id=environment_id,
            )
            logger.warning(
                "tool_routing_contract_incompatible",
                tool_slug=tool_slug,
                tool_contract_version=tool_version.contract_version,
            )
            raise ToolVersionUnavailableError(
                f"Tool '{tool_slug}' contract version "
                f"'{tool_version.contract_version}' is incompatible.",
                metadata={"routing_decision": decision.model_dump(mode="json")},
            )

        # -------------------------------------------------------------------
        # 4. Permission enforcement
        # -------------------------------------------------------------------
        permission_check = self._permissions.build_check(
            tool_manifest=tool_version.manifest,
            agent_manifest=agent_manifest,
            security_context=security_context,
            task_constraints=task_constraints,
            current_tool_calls=current_tool_calls,
        )
        permission_decision = self._permissions.evaluate(permission_check)

        # -------------------------------------------------------------------
        # 5. Translate permission outcome into routing outcome
        # -------------------------------------------------------------------
        if permission_decision.is_denied:
            rejections.append(
                ToolRouteRejection(
                    candidate=selected_candidate,
                    reason=ToolRouteRejectionReason.PERMISSION_DENIED,
                    detail=", ".join(
                        r.value for r in permission_decision.denial_reasons
                    ),
                ),
            )
            decision = ToolRoutingDecision(
                request_id=req_id,
                tool_slug=tool_slug,
                requested_version=requested_version,
                status=ToolRouteStatus.DENIED,
                selected_candidate=None,
                candidates_considered=all_candidates,
                rejections=rejections,
                permission_decision=permission_decision,
                decided_at=datetime.now(timezone.utc),
                decision_latency_ms=int((time.perf_counter() - start_time) * 1000),
                environment_id=environment_id,
            )
            logger.warning(
                "tool_routing_denied",
                tool_slug=tool_slug,
                reasons=[r.value for r in permission_decision.denial_reasons],
            )
            raise ToolPermissionDeniedError(
                f"Tool '{tool_slug}' denied by permission engine.",
                metadata={"routing_decision": decision.model_dump(mode="json")},
            )

        if permission_decision.requires_approval:
            decision = ToolRoutingDecision(
                request_id=req_id,
                tool_slug=tool_slug,
                requested_version=requested_version,
                status=ToolRouteStatus.APPROVAL_REQUIRED,
                selected_candidate=selected_candidate,
                candidates_considered=all_candidates,
                rejections=rejections,
                permission_decision=permission_decision,
                decided_at=datetime.now(timezone.utc),
                decision_latency_ms=int((time.perf_counter() - start_time) * 1000),
                environment_id=environment_id,
            )
            logger.info(
                "tool_routing_approval_required",
                tool_slug=tool_slug,
                tool_version=tool_version.version,
            )
            raise ToolApprovalRequiredError(
                f"Tool '{tool_slug}' requires approval before execution.",
                approval_request_id="pending",
                metadata={"routing_decision": decision.model_dump(mode="json")},
            )

        # -------------------------------------------------------------------
        # 6. Build final RESOLVED decision
        # -------------------------------------------------------------------
        decision = ToolRoutingDecision(
            request_id=req_id,
            tool_slug=tool_slug,
            requested_version=requested_version,
            status=ToolRouteStatus.RESOLVED,
            selected_candidate=selected_candidate,
            candidates_considered=all_candidates,
            rejections=rejections,
            permission_decision=permission_decision,
            decided_at=datetime.now(timezone.utc),
            decision_latency_ms=int((time.perf_counter() - start_time) * 1000),
            environment_id=environment_id,
        )

        logger.info(
            "tool_routing_resolved",
            tool_slug=tool_slug,
            tool_version=tool_version.version,
            decision_latency_ms=decision.decision_latency_ms,
        )

        return ResolvedToolRoute(
            tool_slug=tool_slug,
            tool_version=tool_version.version,
            tool_version_id=tool_version.id,
            tool_manifest=tool_version.manifest,
            implementation_class=tool_version.implementation_class,
            environment_id=environment_id,
            routing_decision=decision,
        )

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    async def _gather_candidates_for_audit(
        self, tool_slug: str, organization_id: str | None,
    ) -> list[ToolRouteCandidate]:
        """Gather all registered versions of a tool for the audit trail."""
        try:
            versions = await self._registry.list_tool_versions(tool_slug)
        except ToolNotFoundError:
            return []
        return [self._to_candidate(v) for v in versions]

    @staticmethod
    def _to_candidate(tool_version: ToolVersion) -> ToolRouteCandidate:
        return ToolRouteCandidate(
            tool_version_id=tool_version.id,
            tool_slug=tool_version.manifest.identity.slug,
            tool_version=tool_version.version,
            contract_version=tool_version.contract_version,
            status=tool_version.status.value,
            implementation_class=tool_version.implementation_class,
        )

    @staticmethod
    def _classify_rejection(
        candidate: ToolRouteCandidate,
        selected: ToolRouteCandidate,
        requested_version: str | None,
    ) -> tuple[ToolRouteRejectionReason, str]:
        """Classify why a candidate was not selected."""
        if requested_version is not None and candidate.tool_version != requested_version:
            return (
                ToolRouteRejectionReason.VERSION_MISMATCH,
                f"Requested version was '{requested_version}'.",
            )
        if candidate.status != "ACTIVE":
            return (
                ToolRouteRejectionReason.STATUS_NOT_ACTIVE,
                f"Candidate status is '{candidate.status}', not ACTIVE.",
            )
        return (
            ToolRouteRejectionReason.VERSION_MISMATCH,
            f"Candidate not selected; chose version '{selected.tool_version}'.",
        )

    def _build_not_found_decision(
        self,
        req_id: str,
        tool_slug: str,
        requested_version: str | None,
        start_time: float,
        environment_id: str | None,
    ) -> ToolRoutingDecision:
        return ToolRoutingDecision(
            request_id=req_id,
            tool_slug=tool_slug,
            requested_version=requested_version,
            status=ToolRouteStatus.NOT_FOUND,
            selected_candidate=None,
            candidates_considered=[],
            rejections=[],
            decided_at=datetime.now(timezone.utc),
            decision_latency_ms=int((time.perf_counter() - start_time) * 1000),
            environment_id=environment_id,
        )

    def _build_version_unavailable_decision(
        self,
        req_id: str,
        tool_slug: str,
        requested_version: str | None,
        start_time: float,
        environment_id: str | None,
    ) -> ToolRoutingDecision:
        return ToolRoutingDecision(
            request_id=req_id,
            tool_slug=tool_slug,
            requested_version=requested_version,
            status=ToolRouteStatus.VERSION_UNAVAILABLE,
            selected_candidate=None,
            candidates_considered=[],
            rejections=[],
            decided_at=datetime.now(timezone.utc),
            decision_latency_ms=int((time.perf_counter() - start_time) * 1000),
            environment_id=environment_id,
        )