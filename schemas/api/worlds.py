"""
DSRT Core — World API Schemas (C3 §54).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from schemas.domain.base import DSRTSchema
from schemas.domain.enums import WorldStatus
from schemas.domain.world import WorldHealth, WorldManifest, WorldPolicy


class WorldRegisterRequest(DSRTSchema):
    """Admin-only: register a world version."""

    manifest: WorldManifest
    implementation_class: str = Field(...)
    make_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorldCreateRequest(DSRTSchema):
    """POST /api/v1/worlds — provision a new world instance."""

    world_slug: str
    world_version: str | None = None
    task_id: str | None = None
    execution_id: str | None = None
    policy_overrides: WorldPolicy | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorldListResponse(DSRTSchema):
    """GET /api/v1/worlds item."""

    id: str
    slug: str
    name: str
    publisher: str
    description: str
    latest_version: str | None


class WorldDetailResponse(DSRTSchema):
    """GET /api/v1/worlds/{id}."""

    id: str
    world_version_id: str
    status: WorldStatus
    organization_id: str
    task_id: str | None
    execution_id: str | None
    environment_instance_ids: list[str]
    policy: WorldPolicy
    configuration_hash: str
    started_at: datetime | None
    stopped_at: datetime | None


class WorldHealthResponse(DSRTSchema):
    """GET /api/v1/worlds/{id}/health."""

    health: WorldHealth