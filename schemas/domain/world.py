"""
DSRT World Domain Schemas (C3 §39-40 + C7 §5-25, §42-48).

C3 laid the foundation. C7 extends with components, state management,
snapshots, network policies, credential isolation, and world templates.

A World is the complete stateful environment against which an execution
can be observed and evaluated (C7 §2).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from schemas.domain.base import DSRTImmutableSchema, DSRTSchema, TimestampedSchema
from schemas.domain.enums import (
    FilesystemAccessMode,
    NetworkMode,
    WorldActionReversibility,
    WorldChangeType,
    WorldClockMode,
    WorldComponentType,
    WorldSnapshotType,
    WorldStatus,
)


# =============================================================================
# C3 World Identity & Manifest (PRESERVED + EXTENDED)
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


class WorldResourceLimits(DSRTSchema):
    """Resource limits for a world instance (C7 §12)."""

    cpu_limit: int = Field(default=4, ge=1)
    memory_mb: int = Field(default=8192, ge=256)
    storage_gb: int = Field(default=20, ge=1)
    max_processes: int = Field(default=100, ge=1)
    max_network_requests: int = Field(default=1000, ge=0)
    max_browser_sessions: int = Field(default=5, ge=0)
    max_duration_seconds: int = Field(default=3600, ge=60)


class WorldComponentSpec(DSRTSchema):
    """Specification for a pluggable world component (C7 §10-11)."""

    component_type: WorldComponentType
    slug: str = Field(..., min_length=1, max_length=120)
    version: str = Field(default="1.0.0")
    configuration: dict[str, Any] = Field(default_factory=dict)
    required: bool = True


class WorldManifest(DSRTImmutableSchema):
    """World manifest — composition of environments + tools + policies + components."""

    identity: WorldIdentity
    description: str = Field(default="", max_length=2000)

    required_environments: list[str] = Field(
        default_factory=list,
        description="Environment slugs that this world provisions.",
    )
    exposed_tools: list[str] = Field(
        default_factory=list,
        description="Tool slugs available to agents inside this world.",
    )

    policy: WorldPolicy = Field(default_factory=WorldPolicy)

    capabilities: list[str] = Field(
        default_factory=list,
        description="High-level capability slugs (e.g. 'research', 'software_engineering').",
    )

    # --- C7 Extensions ---
    components: list[WorldComponentSpec] = Field(
        default_factory=list,
        description="Pluggable world components (C7 §10).",
    )
    services: list[str] = Field(
        default_factory=list,
        description="Service slugs (postgres, redis, etc.) (C7 §9).",
    )
    resources: WorldResourceLimits = Field(
        default_factory=WorldResourceLimits,
        description="Resource limits for instances (C7 §12).",
    )
    clock_mode: WorldClockMode = Field(
        default=WorldClockMode.REAL_TIME,
        description="World time mode (C7 §21).",
    )
    simulation_date: str | None = Field(
        default=None,
        description="ISO date for FIXED_TIME/SIMULATED_TIME modes.",
    )

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
# C3 World Instance / State (PRESERVED + EXTENDED)
# =============================================================================


class WorldObservation(DSRTSchema):
    """A snapshot observation of world state (C7 §42)."""

    world_id: str
    timestamp: datetime
    source: str = ""
    state: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorldSnapshot(DSRTSchema):
    """World snapshot reference (C7 §17-18)."""

    id: str
    world_id: str
    snapshot_type: str = Field(
        default="checkpoint",
        description="base | checkpoint | evaluation",
    )
    storage_reference: str | None = None
    configuration_hash: str
    state_hash: str
    size_bytes: int = Field(default=0, ge=0)
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorldHealth(DSRTSchema):
    """Operational health of a world instance (C7 §38)."""

    world_id: str
    status: WorldStatus
    components: dict[str, str] = Field(default_factory=dict)
    environment_health: dict[str, str] = Field(
        default_factory=dict,
        description="Health status per environment instance.",
    )
    cpu_usage: float = Field(default=0.0, ge=0.0, le=1.0)
    memory_usage_mb: int = Field(default=0, ge=0)
    storage_usage_mb: int = Field(default=0, ge=0)
    network_status: str = "healthy"
    last_heartbeat: datetime | None = None
    detail: str | None = None

class WorldProvisionRequest(DSRTSchema):
    """Request to provision a concrete world instance (C7 §5, §36)."""

    world_slug: str = Field(..., min_length=1)
    world_version: str | None = None
    organization_id: str = Field(..., min_length=1)
    task_id: str | None = None
    execution_id: str | None = None
    policy_overrides: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    
class WorldInstance(TimestampedSchema):
    """A concrete world instance (C7 §7, §14)."""

    id: str
    world_version_id: str

    organization_id: str
    task_id: str | None = None
    execution_id: str | None = None

    status: WorldStatus

    environment_instance_ids: list[str] = Field(default_factory=list)

    policy: WorldPolicy = Field(default_factory=WorldPolicy)
    configuration_hash: str

    # --- C7 Extensions ---
    resource_profile: dict[str, Any] = Field(default_factory=dict)
    clock_mode: str = Field(default="real_time")
    simulation_date: str | None = None

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
    implementation_class: str = Field(
        ...,
        description="Dotted path to the world runtime implementation.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# C7 New Schemas — Components, State, Diffs, Network, Credentials
# =============================================================================


class WorldComponent(DSRTSchema):
    """A running world component instance (C7 §10-11)."""

    id: str
    world_instance_id: str
    component_type: WorldComponentType
    slug: str
    version: str = "1.0.0"
    status: str = "INITIALIZING"
    configuration: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    health_status: str = "unknown"


class WorldState(DSRTSchema):
    """Versioned world state snapshot (C7 §15-16)."""

    id: str
    world_instance_id: str
    version: int = 1
    filesystem_state: dict[str, Any] = Field(default_factory=dict)
    database_state: dict[str, Any] = Field(default_factory=dict)
    browser_state: dict[str, Any] = Field(default_factory=dict)
    application_state: dict[str, Any] = Field(default_factory=dict)
    environment_variables: dict[str, str] = Field(default_factory=dict)
    network_state: dict[str, Any] = Field(default_factory=dict)
    installed_packages: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


class WorldChange(DSRTSchema):
    """A single world state change (C7 §46)."""

    change_type: WorldChangeType
    component: str
    target: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    reversibility: WorldActionReversibility = WorldActionReversibility.REVERSIBLE
    timestamp: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorldStateDiff(DSRTSchema):
    """Diff between two world state snapshots (C7 §45-46)."""

    world_id: str
    before_snapshot_id: str
    after_snapshot_id: str
    changes: list[WorldChange] = Field(default_factory=list)
    total_changes: int = 0


class WorldNetworkPolicy(DSRTSchema):
    """Network access policy for a world instance (C7 §22-23)."""

    mode: NetworkMode = NetworkMode.CONTROLLED
    allowed_domains: list[str] = Field(default_factory=list)
    blocked_domains: list[str] = Field(default_factory=list)
    allowed_ports: list[int] = Field(default_factory=lambda: [80, 443])
    max_outbound_requests: int = Field(default=1000, ge=0)
    rate_limit_per_minute: int = Field(default=60, ge=0)
    proxy_url: str | None = None
    log_all_requests: bool = True


class WorldCredentialRef(DSRTSchema):
    """A credential reference injected into a world (C7 §24-25).

    Agents receive permission to use 'credential://github/read',
    not the raw secret.
    """

    credential_ref: str = Field(
        ...,
        description="e.g., 'credential://github/read'",
    )
    provider: str
    scope: str = "read"
    injected_into: list[str] = Field(
        default_factory=list,
        description="Component slugs that receive this credential.",
    )


class WorldTemplate(DSRTSchema):
    """A reusable world template (C7 §49)."""

    slug: str = Field(..., min_length=3, max_length=120)
    name: str
    description: str = ""
    base_manifest: WorldManifest
    default_policy_overrides: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)