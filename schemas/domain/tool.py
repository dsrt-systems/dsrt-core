"""
DSRT Tool Domain Schemas (C3).

The frozen contracts that define every tool in DSRT:
  - ToolIdentity, ToolManifest — immutable descriptors
  - ToolPermissionDeclaration — what a tool requires
  - ToolLimits, ToolRetryPolicy — operational constraints
  - ToolExecutionRequest, ToolExecutionResult — the runtime contract
  - ToolObservation — structured tool output
  - ToolHealth, ToolUsage — operational metrics

Agents never construct these directly; they are built by Core and the SDK.

NOTE ON NAMING
--------------
Three distinct "tool error" concepts exist in DSRT. They must never be conflated:

  * `schemas.domain.model_fabric.ModelError`
        → a normalized model/provider error (C2).

  * `schemas.domain.tool.ToolExecutionError`  (defined here)
        → a *serializable error record* stored inside a ToolExecutionResult.

  * `core.tools.errors.ToolFabricError`
        → a Python *exception* raised at runtime inside Core.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field, model_validator

from schemas.domain.base import DSRTImmutableSchema, DSRTSchema, TimestampedSchema
from schemas.domain.enums import (
    FilesystemAccessMode,
    NetworkMode,
    ObservationType,
    SideEffectClass,
    ToolExecutionStatus,
    ToolHealthStatus,
    ToolRiskLevel,
    ToolStatus,
)


# =============================================================================
# 1. Tool Identity
# =============================================================================


class ToolIdentity(DSRTImmutableSchema):
    """Immutable tool identity (C3 §5, §6)."""

    slug: str = Field(
        ...,
        min_length=3,
        max_length=120,
        description="Globally unique tool slug (e.g. 'web.search').",
    )
    name: str = Field(..., min_length=1, max_length=200)
    version: str = Field(
        ..., min_length=1, max_length=64, description="Tool version (semver)."
    )
    contract_version: str = Field(
        default="1.0",
        description="DSRT Tool Contract version this tool implements.",
    )
    publisher: str = Field(
        default="dsrt",
        description="Publisher identifier (e.g. 'dsrt', 'enterprise', or an organization slug).",
    )
    category: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Tool category (e.g. 'web', 'filesystem', 'python', 'http').",
    )


# =============================================================================
# 2. Tool Permissions
# =============================================================================


class ToolNetworkPermission(DSRTImmutableSchema):
    """Network permissions declared by a tool (C3 §11, §23)."""

    required: bool = False
    outbound: bool = False
    inbound: bool = False
    allowed_domains: list[str] = Field(default_factory=list)
    blocked_domains: list[str] = Field(default_factory=list)
    mode: NetworkMode = NetworkMode.RESTRICTED


class ToolFilesystemPermission(DSRTImmutableSchema):
    """Filesystem permissions declared by a tool (C3 §11, §24, §25)."""

    read: bool = False
    write: bool = False
    delete: bool = False
    access_mode: FilesystemAccessMode = FilesystemAccessMode.NONE


class ToolBrowserPermission(DSRTImmutableSchema):
    """Browser permissions declared by a tool (C3 §23)."""

    control: bool = False
    downloads: bool = False
    uploads: bool = False


class ToolCredentialPermission(DSRTImmutableSchema):
    """Credential access permissions declared by a tool (C3 §30, §53)."""

    access: bool = False
    credential_refs: list[str] = Field(
        default_factory=list,
        description="Credential references the tool is permitted to use.",
    )


class ToolPermissionDeclaration(DSRTImmutableSchema):
    """Complete permission declaration for a tool (C3 §11)."""

    network: ToolNetworkPermission = Field(default_factory=ToolNetworkPermission)
    filesystem: ToolFilesystemPermission = Field(
        default_factory=ToolFilesystemPermission
    )
    browser: ToolBrowserPermission = Field(default_factory=ToolBrowserPermission)
    credentials: ToolCredentialPermission = Field(
        default_factory=ToolCredentialPermission
    )
    external_actions: bool = Field(
        default=False,
        description="Tool may perform external actions (email, payments, etc.).",
    )


# =============================================================================
# 3. Tool Operational Policy
# =============================================================================


class ToolRetryPolicy(DSRTImmutableSchema):
    """Retry behaviour declared by a tool (C3 §47)."""

    allowed: bool = True
    max_attempts: int = Field(default=1, ge=1, le=10)
    idempotent: bool = Field(
        default=True,
        description="Must be True for automatic retry to be permitted.",
    )
    backoff_seconds: float = Field(default=1.0, ge=0.0)
    backoff_multiplier: float = Field(default=2.0, ge=1.0)
    max_backoff_seconds: float = Field(default=30.0, ge=0.0)

    @model_validator(mode="after")
    def _validate_retry(self) -> ToolRetryPolicy:
        if self.allowed and not self.idempotent and self.max_attempts > 1:
            raise ValueError(
                "Non-idempotent tools must not declare max_attempts > 1."
            )
        return self


class ToolLimits(DSRTImmutableSchema):
    """Operational limits declared by a tool (C3 §6, §37, §50)."""

    timeout_seconds: int = Field(default=30, ge=1, le=3600)
    max_output_bytes: int = Field(
        default=10 * 1024 * 1024,
        ge=0,
        description="Maximum raw output size (bytes).",
    )
    max_memory_mb: int | None = Field(default=None, ge=0)
    max_cpu_cores: float | None = Field(default=None, ge=0)
    max_concurrent_calls: int = Field(default=5, ge=1)


class ToolCapabilityDeclaration(DSRTImmutableSchema):
    """Capability a tool provides (C3 §6, §7)."""

    slug: str = Field(..., min_length=3, max_length=120)
    description: str = Field(default="", max_length=1000)


# =============================================================================
# 4. Tool Manifest
# =============================================================================


class ToolManifest(DSRTImmutableSchema):
    """Complete tool manifest — the machine-readable contract (C3 §6)."""

    identity: ToolIdentity
    description: str = Field(default="", max_length=2000)

    capabilities: list[ToolCapabilityDeclaration] = Field(default_factory=list)

    permissions: ToolPermissionDeclaration = Field(
        default_factory=ToolPermissionDeclaration
    )
    risk_level: ToolRiskLevel = ToolRiskLevel.LOW
    side_effect: SideEffectClass = SideEffectClass.READ

    limits: ToolLimits = Field(default_factory=ToolLimits)
    retry: ToolRetryPolicy = Field(default_factory=ToolRetryPolicy)

    input_schema: dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema for tool input."
    )
    output_schema: dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema for tool output."
    )

    requires_approval: bool = Field(
        default=False,
        description="If true, every invocation requires human approval.",
    )
    requires_environment: bool = Field(
        default=False,
        description="If true, the tool requires a specific environment to execute.",
    )
    environment_type: str | None = Field(
        default=None, description="Required environment type slug."
    )

    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_manifest(self) -> ToolManifest:
        # Capability slugs must be unique within a manifest.
        slugs = [c.slug for c in self.capabilities]
        if len(slugs) != len(set(slugs)):
            raise ValueError("Capability slugs within a manifest must be unique.")
        return self


# =============================================================================
# 5. Tool Context (passed to tool.initialize)
# =============================================================================


class ToolContext(DSRTImmutableSchema):
    """Immutable context passed to a tool during initialize (C3 §5)."""

    execution_id: str
    task_id: str
    organization_id: str
    agent_slug: str
    agent_version: str
    environment_id: str | None = None
    workspace_root: str | None = Field(
        default=None,
        description="Absolute path to the execution workspace, if any.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolInitializationResult(DSRTImmutableSchema):
    """Result of DSRTTool.initialize (C3 §5)."""

    ready: bool
    message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# 6. Tool Execution Request
# =============================================================================


class ToolExecutionRequest(DSRTSchema):
    """Canonical tool execution request (C3 §17)."""

    request_id: str = Field(
        ...,
        description="Unique request identifier for idempotency and correlation.",
    )
    tool_slug: str
    tool_version: str | None = None

    execution_id: str
    task_id: str
    organization_id: str
    agent_slug: str
    agent_version: str

    arguments: dict[str, Any] = Field(default_factory=dict)

    environment_id: str | None = None
    timeout_seconds: int | None = None

    idempotency_key: str | None = None
    attempt: int = Field(default=1, ge=1)

    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# 7. Tool Observation
# =============================================================================


class ToolObservation(DSRTSchema):
    """Structured observation produced by a tool (C3 §19)."""

    observation_id: str
    observation_type: ObservationType

    content: Any = Field(
        default=None,
        description="Observation content (text, structured data, or artifact reference).",
    )
    summary: str | None = Field(
        default=None,
        max_length=4000,
        description="Short human-readable summary.",
    )

    source: str = Field(
        default="", description="Which tool / component emitted the observation."
    )
    timestamp: datetime

    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    truncated: bool = False
    size_bytes: int = Field(default=0, ge=0)

    artifact_id: str | None = None

    provenance: dict[str, Any] = Field(
        default_factory=dict,
        description="Provenance chain back to tool_execution_id → request → agent → execution.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolObservationCreate(DSRTSchema):
    """Internal payload the Execution Engine uses to create an observation."""

    observation_type: ObservationType
    content: Any = None
    summary: str | None = None
    source: str = ""
    confidence: float | None = None
    truncated: bool = False
    size_bytes: int = 0
    artifact_id: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# 8. Tool Execution Error (serializable error record)
# =============================================================================


class ToolExecutionError(DSRTSchema):
    """Normalized error entry inside a ToolExecutionResult (C3 §35, §46).

    This is a *data structure* — not an exception. Exceptions raised by tool
    implementations live in `core.tools.errors`.
    """

    code: str
    message: str
    retryable: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# 9. Tool Usage (resource accounting)
# =============================================================================


class ToolUsage(DSRTSchema):
    """Resource usage recorded for a tool execution (C3 §50)."""

    duration_ms: int = Field(default=0, ge=0)
    cpu_ms: int | None = Field(default=None, ge=0)
    memory_mb_peak: float | None = Field(default=None, ge=0)
    network_bytes_in: int | None = Field(default=None, ge=0)
    network_bytes_out: int | None = Field(default=None, ge=0)
    storage_bytes: int | None = Field(default=None, ge=0)
    external_api_calls: int = Field(default=0, ge=0)
    estimated_cost_usd: Decimal | None = Field(default=None, ge=0)


# =============================================================================
# 10. Tool Execution Result
# =============================================================================


class ToolExecutionResult(DSRTSchema):
    """Canonical tool execution result (C3 §18)."""

    request_id: str
    tool_execution_id: str

    tool_slug: str
    tool_version: str

    status: ToolExecutionStatus

    output: Any = Field(
        default=None,
        description="Primary structured output (may be redacted / summarized).",
    )
    observations: list[ToolObservation] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    errors: list[ToolExecutionError] = Field(default_factory=list)

    usage: ToolUsage = Field(default_factory=ToolUsage)

    duration_ms: int = Field(default=0, ge=0)
    attempt: int = Field(default=1, ge=1)

    started_at: datetime | None = None
    completed_at: datetime | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# 11. Tool Health
# =============================================================================


class ToolHealth(DSRTSchema):
    """Operational health of a tool (C3 §51)."""

    tool_slug: str
    tool_version: str
    status: ToolHealthStatus

    recent_calls: int = Field(default=0, ge=0)
    recent_failures: int = Field(default=0, ge=0)
    recent_timeouts: int = Field(default=0, ge=0)

    error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    avg_latency_ms: float = Field(default=0.0, ge=0.0)
    p95_latency_ms: float = Field(default=0.0, ge=0.0)

    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None

    detail: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# 12. Registry Views
# =============================================================================


class Tool(TimestampedSchema):
    """Registered tool (registry view)."""

    id: str
    organization_id: str | None = Field(
        default=None, description="Null for system-wide tools."
    )
    slug: str
    name: str
    category: str
    publisher: str
    description: str = ""
    status: ToolStatus
    latest_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolVersion(TimestampedSchema):
    """A specific tool version (registry view)."""

    id: str
    tool_id: str
    version: str
    contract_version: str
    status: ToolStatus
    manifest: ToolManifest
    implementation_class: str = Field(
        ...,
        description="Dotted path to the DSRTTool implementation "
        "(e.g. 'core.tools.builtins.web_search:WebSearchTool').",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCapabilityLink(DSRTSchema):
    """Links a tool version to a capability slug it provides."""

    id: str
    tool_version_id: str
    capability_slug: str
    description: str = ""