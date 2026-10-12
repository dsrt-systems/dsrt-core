"""
DSRT Core — Environment API Schemas (C3 §54).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from schemas.domain.base import DSRTSchema
from schemas.domain.enums import EnvironmentStatus, EnvironmentType
from schemas.domain.environment import (
    EnvironmentFilesystemPolicy,
    EnvironmentHealth,
    EnvironmentManifest,
    EnvironmentNetworkPolicy,
    EnvironmentResourceLimits,
    EnvironmentSnapshot,
)


class EnvironmentRegisterRequest(DSRTSchema):
    """Admin-only: register an environment version."""

    manifest: EnvironmentManifest
    implementation_class: str = Field(..., description="Dotted path to the environment runtime implementation.")
    make_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class EnvironmentCreateRequest(DSRTSchema):
    """Create a new environment instance (C3 §54)."""

    environment_slug: str
    environment_version: str | None = None
    task_id: str | None = None
    execution_id: str | None = None
    world_id: str | None = None
    resource_overrides: EnvironmentResourceLimits | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EnvironmentListResponse(DSRTSchema):
    """GET /api/v1/environments item."""

    id: str
    environment_type: EnvironmentType
    status: EnvironmentStatus
    task_id: str | None
    execution_id: str | None
    world_id: str | None
    started_at: datetime | None


class EnvironmentDetailResponse(DSRTSchema):
    """GET /api/v1/environments/{id}."""

    id: str
    environment_version_id: str
    environment_type: EnvironmentType
    status: EnvironmentStatus

    organization_id: str
    task_id: str | None
    execution_id: str | None
    world_id: str | None

    workspace_root: str | None
    resource_profile: EnvironmentResourceLimits
    network_policy: EnvironmentNetworkPolicy
    filesystem_policy: EnvironmentFilesystemPolicy

    started_at: datetime | None
    stopped_at: datetime | None


class EnvironmentHealthResponse(DSRTSchema):
    """GET /api/v1/environments/{id}/health."""

    health: EnvironmentHealth


class EnvironmentSnapshotResponse(DSRTSchema):
    """POST /api/v1/environments/{id}/snapshot."""

    snapshot: EnvironmentSnapshot