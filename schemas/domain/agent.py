"""
Agent, AgentVersion, and Agent Manifest schemas.

The AgentManifest is one of the most important contracts in DSRT.
"""

from __future__ import annotations

from pydantic import Field, field_validator

from schemas.domain.base import DSRTSchema, TimestampedSchema
from schemas.domain.enums import AgentStatus, AgentVersionStatus


class AgentIdentity(DSRTSchema):
    """Immutable identity block declared in manifest.yaml."""

    id: str = Field(
        pattern=r"^[a-z][a-z0-9_]*$",
        min_length=2,
        max_length=200,
    )
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    contract_version: str = Field(pattern=r"^\d+\.\d+$")
    publisher: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)


class AgentRequirements(DSRTSchema):
    """Agent-declared requirements — C1 §13."""

    minimum_core_version: str = Field(pattern=r"^\d+\.\d+(\.\d+)?$")
    required_capabilities: list[str] = Field(default_factory=list)
    optional_capabilities: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    optional_tools: list[str] = Field(default_factory=list)


class NetworkPermission(DSRTSchema):
    required: bool = False


class FilesystemPermission(DSRTSchema):
    access: str = Field(default="none", pattern=r"^(none|workspace|full)$")


class BrowserPermission(DSRTSchema):
    access: bool = False


class ExternalActionsPermission(DSRTSchema):
    access: bool = False


class AgentPermissions(DSRTSchema):
    """Agent-requested permissions — C1 §37."""

    network: NetworkPermission = Field(default_factory=NetworkPermission)
    filesystem: FilesystemPermission = Field(default_factory=FilesystemPermission)
    browser: BrowserPermission = Field(default_factory=BrowserPermission)
    external_actions: ExternalActionsPermission = Field(default_factory=ExternalActionsPermission)


class AgentManifest(DSRTSchema):
    """The complete AgentManifest contract."""

    identity: AgentIdentity
    capabilities: list[str] = Field(min_length=1)
    requirements: AgentRequirements
    permissions: AgentPermissions = Field(default_factory=AgentPermissions)
    configuration: dict = Field(default_factory=dict)
    description: str = ""

    @field_validator("capabilities")
    @classmethod
    def _validate_capabilities(cls, v: list[str]) -> list[str]:
        for cap in v:
            stripped = cap.replace("_", "").replace(".", "")
            if not stripped.isalnum():
                raise ValueError(f"Invalid capability slug: {cap}")
        return v


class AgentRegistrationRequest(DSRTSchema):
    manifest: AgentManifest
    package_reference: str = Field(min_length=1, max_length=500)


class Agent(TimestampedSchema):
    id: str
    slug: str
    name: str
    description: str
    category: str
    publisher: str
    status: AgentStatus


class AgentVersion(TimestampedSchema):
    id: str
    agent_id: str
    version: str
    contract_version: str
    manifest: AgentManifest
    package_reference: str
    configuration: dict
    requirements: AgentRequirements
    permissions: AgentPermissions
    status: AgentVersionStatus