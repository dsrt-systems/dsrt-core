"""
DSRT World Domain Schemas (C3 §39-40).

C3 lays the foundation for Worlds — the full Arena World system arrives in C7.
A World is a composition of environments + tools + policies + data that provides
a coherent stateful place where an agent can operate.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from schemas.domain.base import DSRTImmutableSchema, DSRTSchema, TimestampedSchema
from schemas.domain.enums import (
    FilesystemAccessMode,
    NetworkMode,
    WorldStatus,
)


# =============================================================================
# World Identity & Manifest
# =============================================================================


class WorldIdentity(DSRTImmutableSchema):
    """Immutable world definition identity."""

    slug: str = Field(..., min_length=3, max_length=120)
    name: str = Field(..., min_length=1, max_length=200)
    version: str = Field(..., min_length=1, max_length=64)
    publisher: str = Field(default="dsrt")


class WorldPolicy(DSRTImmutableSchema):
    """Policy enforced on all tools and environments inside a world."""

    network_mode: NetworkMode = NetworkMode.CONTROLLED
    allowed_domains: list[str] = Field(default_factory=list)
    blocked_domains: list[str] = Field(default_factory=list)
    filesystem_access: FilesystemAccessMode = FilesystemAccessMode.WORKSPACE
    allow_external_actions: bool = False
    require_approval_for_external: bool = True


class WorldManifest(DSRTImmutableSchema):
    """World manifest — composition of environments + tools + policies."""

    identity: WorldIdentity
    description: str = Field(default="", max_length=2000)

    required_environments: list[str] = Field(default_factory=list, description="Environment slugs that this world provisions.")
    exposed_tools: list[str] = Field(default_factory=list, description="Tool slugs available to agents inside this world.")

    policy: WorldPolicy = Field(default_factory=WorldPolicy)

    capabilities: list[str] = Field(default_factory=list, description="High-level capability slugs this world provides (e.g. 'research', 'software_engineering').")

    reset_supported: bool = True
    snapshot_supported: bool = False

    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate(self) -> WorldManifest:
        if len(self.exposed_tools) != len(set(self.exposed_tools)):
            raise ValueError("exposed_tools must contain unique slugs.")
        if len(self.required_environments) != len(set(self.required_environments)):
            raise ValueError("required_environments must contain unique slugs.")
        return self


# =============================================================================
# World Instance / State
# =============================================================================


class WorldObservation(DSRTSchema):
    """A snapshot observation of world state (foundation for C7)."""

    world_id: str
    timestamp: datetime
    source: str = ""
    state: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorldSnapshot(DSRTSchema):
    """World snapshot reference (foundation for C7 §17)."""

    id: str
    world_id: str
    snapshot_type: str = Field(default="checkpoint", description="base | checkpoint | evaluation")
    storage_reference: str | None = None
    configuration_hash: str
    state_hash: str
    size_bytes: int = Field(default=0, ge=0)
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorldHealth(DSRTSchema):
    """Operational health of a world instance (C3 §38 analog)."""

    world_id: str
    status: WorldStatus
    components: dict[str, str] = Field(default_factory=dict)
    environment_health: dict[str, str] = Field(default_factory=dict, description="Health status per environment instance.")
    last_heartbeat: datetime | None = None
    detail: str | None = None


class WorldInstance(TimestampedSchema):
    """A concrete world instance."""

    id: str
    world_version_id: str

    organization_id: str
    task_id: str | None = None
    execution_id: str | None = None

    status: WorldStatus

    environment_instance_ids: list[str] = Field(default_factory=list)

    policy: WorldPolicy = Field(default_factory=WorldPolicy)
    configuration_hash: str

    started_at: datetime | None = None
    stopped_at: datetime | None = None
    destroyed_at: datetime | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)


class World(TimestampedSchema):
    """Registered world definition (registry view)."""

    id: str
    slug: str
    name: str
    publisher: str
    description: str = ""
    latest_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorldVersion(TimestampedSchema):
    """A specific world version (registry view)."""

    id: str
    world_id: str
    version: str
    manifest: WorldManifest
    implementation_class: str = Field(..., description="Dotted path to the world runtime implementation.")
    metadata: dict[str, Any] = Field(default_factory=dict)