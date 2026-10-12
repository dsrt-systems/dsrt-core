"""
DSRT Core — Approval API Schemas (C3 §15).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from schemas.domain.approval import ApprovalDecisionCreate
from schemas.domain.base import DSRTSchema
from schemas.domain.enums import ApprovalStatus, SideEffectClass, ToolRiskLevel


class ApprovalListResponse(DSRTSchema):
    """GET /api/v1/approvals item."""

    id: str
    execution_id: str
    tool_slug: str
    tool_version: str
    requested_action: str
    risk_level: ToolRiskLevel
    side_effect: SideEffectClass
    status: ApprovalStatus
    expires_at: datetime | None
    created_at: datetime


class ApprovalDetailResponse(DSRTSchema):
    """GET /api/v1/approvals/{id}."""

    id: str
    organization_id: str
    execution_id: str
    tool_execution_id: str
    tool_slug: str
    tool_version: str
    requested_action: str
    risk_level: ToolRiskLevel
    side_effect: SideEffectClass
    status: ApprovalStatus
    reason: str
    expires_at: datetime | None
    arguments_preview: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ApprovalDecisionRequest(ApprovalDecisionCreate):
    """POST /api/v1/approvals/{id}/decide — alias of ApprovalDecisionCreate."""

    pass


class ApprovalDecisionResponse(DSRTSchema):
    """Response after submitting a decision."""

    approval_request_id: str
    decision: ApprovalStatus
    decided_by_user_id: str
    decided_at: datetime