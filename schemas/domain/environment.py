"""
DSRT Environment Domain Schemas (C3).

The frozen contracts for Environment Runtimes (C3 §33-38) — the controlled
runtimes in which tools operate (browser, python sandbox, container, etc.).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from schemas.domain.base import DSRTImmutableSchema, DSRTSchema, TimestampedSchema
from schemas.domain.enums import (
    EnvironmentHealthStatus,
    EnvironmentStatus,
    EnvironmentType,
    FilesystemAccessMode,
    NetworkMode,
)


# =============================================================================
# Environment Identity & Manifest
# =============================================================================


class EnvironmentIdentity(DSRTImmutableSchema):
    """Immutable environment definition identity."""

    slug: str = Field(..., min_length=3, max_length=120)
    name: str = Field(..., min_length=1, max_length=200)
    version: str = Field(..., min_length=1, max_length=64)
    environment_type: EnvironmentType
    publisher: str = Field(default="dsrt")


class EnvironmentResourceLimits(DSRTImmutableSchema):
    """Per-environment resource limits (C3 §37)."""

    max_cpu_cores: float = Field(default=2.0, ge=0.0)
    max_memory_mb: int = Field(default=4096, ge=0)
    max_disk_mb: int = Field(default=10000, ge=0)
    max_duration_seconds: int = Field(default=1800, ge=0)
    max_network_requests: int = Field(default=500, ge=0)
    max_concurrent_tools: int = Field(default=5, ge=1)


class EnvironmentNetworkPolicy(DSRTImmutableSchema):
    """Network policy applied to all tools running in the environment."""

    mode: NetworkMode = NetworkMode.RESTRICTED
    allowed_domains: list[str] = Field(default_factory=list)
    blocked_domains: list[str] = Field(default_factory=list)
    allow_downloads: bool = True
    allow_uploads: bool = False


class EnvironmentFilesystemPolicy(DSRTImmutableSchema):
    """Filesystem policy applied to tools (C3 §24, §25)."""

    access_mode: FilesystemAccessMode = FilesystemAccessMode.WORKSPACE
    workspace_quota_mb: int = Field(default=1000, ge=0)
    allow_delete: bool = False


class EnvironmentManifest(DSRTImmutableSchema):
    """Complete environment manifest (C3 §33)."""

    identity: EnvironmentIdentity
    description: str = Field(default="", max_length=2000)

    installed_tools: list[str] = Field(default_factory=list, description="Tool slugs available in this environment.")
    environment_variables: dict[str, str] = Field(default_factory=dict)

    resources: EnvironmentResourceLimits = Field(default_factory=EnvironmentResourceLimits)
    network: EnvironmentNetworkPolicy = Field(default_factory=EnvironmentNetworkPolicy)
    filesystem: EnvironmentFilesystemPolicy = Field(default_factory=EnvironmentFilesystemPolicy)

    base_image: str | None = Field(default=None, description="For container environments: base image reference.")

    snapshot_supported: bool = False
    reset_supported: bool = True

    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate(self) -> EnvironmentManifest:
        slugs = self.installed_tools
        if len(slugs) != len(set(slugs)):
            raise ValueError("installed_tools must contain unique tool slugs.")
        return self


# =============================================================================
# Environment Instance
# =============================================================================


class EnvironmentResources(DSRTSchema):
    """Live resource usage snapshot of an environment instance."""

    cpu_cores_used: float = Field(default=0.0, ge=0.0)
    memory_mb_used: int = Field(default=0, ge=0)
    disk_mb_used: int = Field(default=0, ge=0)
    network_requests: int = Field(default=0, ge=0)
    uptime_seconds: int = Field(default=0, ge=0)


class EnvironmentHealth(DSRTSchema):
    """Operational health of an environment instance (C3 §38)."""

    environment_id: str
    status: EnvironmentHealthStatus
    components: dict[str, str] = Field(default_factory=dict)
    resources: EnvironmentResources = Field(default_factory=EnvironmentResources)
    last_heartbeat: datetime | None = None
    detail: str | None = None


class EnvironmentSnapshot(DSRTSchema):
    """Snapshot of an environment at a point in time (C3 §38)."""

    id: str
    environment_id: str
    snapshot_type: str = Field(default="checkpoint", description="base | checkpoint | evaluation")
    storage_reference: str | None = None
    state_hash: str
    configuration_hash: str
    size_bytes: int = Field(default=0, ge=0)
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class EnvironmentInstance(TimestampedSchema):
    """A concrete environment instance (C3 §36)."""

    id: str
    environment_version_id: str
    environment_type: EnvironmentType

    organization_id: str
    task_id: str | None = None
    execution_id: str | None = None
    world_id: str | None = None

    status: EnvironmentStatus
    workspace_root: str | None = None
    runtime_reference: str | None = Field(default=None, description="Opaque reference to the underlying runtime (container id, process id, etc.).")

    resource_profile: EnvironmentResourceLimits = Field(default_factory=EnvironmentResourceLimits)
    network_policy: EnvironmentNetworkPolicy = Field(default_factory=EnvironmentNetworkPolicy)
    filesystem_policy: EnvironmentFilesystemPolicy = Field(default_factory=EnvironmentFilesystemPolicy)

    started_at: datetime | None = None
    stopped_at: datetime | None = None
    destroyed_at: datetime | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)


class Environment(TimestampedSchema):
    """Registered environment definition (registry view)."""

    id: str
    slug: str
    name: str
    environment_type: EnvironmentType
    publisher: str
    description: str = ""
    latest_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EnvironmentVersion(TimestampedSchema):
    """A specific environment version (registry view)."""

    id: str
    environment_id: str
    version: str
    manifest: EnvironmentManifest
    implementation_class: str = Field(..., description="Dotted path to the environment runtime implementation.")
    metadata: dict[str, Any] = Field(default_factory=dict)