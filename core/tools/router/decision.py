"""
Tool Routing Decision Records (C3 §10, §44).

Immutable, auditable records produced by the ToolRouter.
Every resolution attempt produces a ToolRoutingDecision that is
persisted to the execution trajectory for C6 verification,
C8 Arena evaluation, and debugging.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field

from schemas.domain.base import DSRTImmutableSchema, DSRTSchema
from schemas.domain.tool import ToolManifest

from core.tools.permissions.decision import ToolPermissionDecision


class ToolRouteStatus(str, Enum):
    """The outcome of a tool routing attempt."""

    RESOLVED = "RESOLVED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    DENIED = "DENIED"
    NOT_FOUND = "NOT_FOUND"
    VERSION_UNAVAILABLE = "VERSION_UNAVAILABLE"


class ToolRouteRejectionReason(str, Enum):
    """Reasons a tool version candidate was rejected during routing (C3 §10)."""

    VERSION_MISMATCH = "VERSION_MISMATCH"
    CONTRACT_VERSION_INCOMPATIBLE = "CONTRACT_VERSION_INCOMPATIBLE"
    STATUS_NOT_ACTIVE = "STATUS_NOT_ACTIVE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    ENVIRONMENT_INCOMPATIBLE = "ENVIRONMENT_INCOMPATIBLE"
    TOOL_UNHEALTHY = "TOOL_UNHEALTHY"


class ToolRouteCandidate(DSRTImmutableSchema):
    """A candidate ToolVersion considered during routing."""

    tool_version_id: str
    tool_slug: str
    tool_version: str
    contract_version: str
    status: str
    implementation_class: str


class ToolRouteRejection(DSRTImmutableSchema):
    """A rejected ToolVersion candidate with its reason."""

    candidate: ToolRouteCandidate
    reason: ToolRouteRejectionReason
    detail: str = Field(default="", max_length=1000)


class ToolRoutingDecision(DSRTImmutableSchema):
    """The complete, auditable record of a tool routing attempt (C3 §10)."""

    request_id: str
    tool_slug: str
    requested_version: str | None = None

    status: ToolRouteStatus
    selected_candidate: ToolRouteCandidate | None = None

    # Audit trail
    candidates_considered: list[ToolRouteCandidate] = Field(default_factory=list)
    rejections: list[ToolRouteRejection] = Field(default_factory=list)

    # Permission decision (if evaluated)
    permission_decision: ToolPermissionDecision | None = None

    # Timing
    decided_at: datetime
    decision_latency_ms: int = Field(default=0, ge=0)

    # Context
    environment_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_resolved(self) -> bool:
        return self.status == ToolRouteStatus.RESOLVED

    @property
    def requires_approval(self) -> bool:
        return self.status == ToolRouteStatus.APPROVAL_REQUIRED

    @property
    def is_denied(self) -> bool:
        return self.status in (
            ToolRouteStatus.DENIED,
            ToolRouteStatus.NOT_FOUND,
            ToolRouteStatus.VERSION_UNAVAILABLE,
        )


class ResolvedToolRoute(DSRTSchema):
    """The execution-ready output of a successful routing resolution.

    Consumed by the Tool Execution Engine (C3.6).
    """

    tool_slug: str
    tool_version: str
    tool_version_id: str
    tool_manifest: ToolManifest
    implementation_class: str
    environment_id: str | None = None
    routing_decision: ToolRoutingDecision