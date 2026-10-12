"""
DSRT Approval Domain Schemas (C3 §15, §49).

Human-in-the-loop approval for HIGH / CRITICAL risk tool actions and
EXTERNAL_ACTION / IRREVERSIBLE side effects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from schemas.domain.base import DSRTSchema, TimestampedSchema
from schemas.domain.enums import (
    ApprovalStatus,
    OrganizationRole,
    SideEffectClass,
    ToolRiskLevel,
)


class ApprovalRequest(TimestampedSchema):
    """An approval request raised during tool execution."""

    id: str
    organization_id: str
    execution_id: str
    tool_execution_id: str

    tool_slug: str
    tool_version: str
    requested_action: str = Field(..., description="Human-readable description of the action requiring approval.")

    risk_level: ToolRiskLevel
    side_effect: SideEffectClass

    required_role: OrganizationRole = OrganizationRole.MEMBER
    reason: str = Field(default="", max_length=2000)

    status: ApprovalStatus = ApprovalStatus.REQUESTED

    expires_at: datetime | None = None

    arguments_preview: dict[str, Any] = Field(default_factory=dict, description="Redacted preview of tool arguments.")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecision(TimestampedSchema):
    """A decision rendered on an approval request."""

    id: str
    approval_request_id: str

    decided_by_user_id: str
    decision: ApprovalStatus = Field(..., description="Must be GRANTED or REJECTED.")
    reason: str = Field(default="", max_length=2000)

    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalCreate(DSRTSchema):
    """Internal payload used by Core to create an approval request."""

    organization_id: str
    execution_id: str
    tool_execution_id: str
    tool_slug: str
    tool_version: str
    requested_action: str
    risk_level: ToolRiskLevel
    side_effect: SideEffectClass
    required_role: OrganizationRole = OrganizationRole.MEMBER
    reason: str = ""
    expires_at: datetime | None = None
    arguments_preview: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecisionCreate(DSRTSchema):
    """Payload submitted by a human to render a decision."""

    decision: ApprovalStatus = Field(..., description="Must be GRANTED or REJECTED.")
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)