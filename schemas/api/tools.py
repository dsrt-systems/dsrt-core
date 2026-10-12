"""
DSRT Core — Tool API Schemas (C3 §54).

Request/response schemas for the Tool REST API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from schemas.domain.base import DSRTSchema
from schemas.domain.enums import (
    SideEffectClass,
    ToolExecutionStatus,
    ToolHealthStatus,
    ToolRiskLevel,
    ToolStatus,
)
from schemas.domain.tool import ToolManifest, ToolObservation, ToolUsage


class ToolRegisterRequest(DSRTSchema):
    """Request to register a tool version (admin-only)."""

    manifest: ToolManifest
    implementation_class: str = Field(..., description="Dotted path, e.g. 'core.tools.builtins.web_search:WebSearchTool'.")
    make_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolListResponse(DSRTSchema):
    """Response payload for GET /api/v1/tools."""

    id: str
    slug: str
    name: str
    category: str
    publisher: str
    description: str
    status: ToolStatus
    latest_version: str | None
    risk_level: ToolRiskLevel
    side_effect: SideEffectClass


class ToolDetailResponse(DSRTSchema):
    """Response payload for GET /api/v1/tools/{slug}."""

    id: str
    slug: str
    name: str
    category: str
    publisher: str
    description: str
    status: ToolStatus
    latest_version: str | None
    manifest: ToolManifest | None = None


class ToolExecuteRequest(DSRTSchema):
    """Request payload for POST /api/v1/tools/execute (admin / testing)."""

    tool_slug: str
    tool_version: str | None = None
    execution_id: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int | None = None
    idempotency_key: str | None = None


class ToolExecuteResponse(DSRTSchema):
    """Response payload for POST /api/v1/tools/execute."""

    request_id: str
    tool_execution_id: str
    tool_slug: str
    tool_version: str
    status: ToolExecutionStatus
    output: Any = None
    observations: list[ToolObservation] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    usage: ToolUsage
    duration_ms: int
    error_code: str | None = None
    error_message: str | None = None


class ToolHealthResponse(DSRTSchema):
    """Response payload for POST /api/v1/tools/{slug}/health."""

    tool_slug: str
    tool_version: str
    status: ToolHealthStatus
    recent_calls: int
    recent_failures: int
    error_rate: float
    avg_latency_ms: float
    last_success_at: datetime | None
    last_failure_at: datetime | None