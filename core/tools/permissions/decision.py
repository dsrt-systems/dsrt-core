"""
Tool Permission Decision Records (C3 §11-15, §48-49, §52).

Immutable, auditable records produced by the ToolPermissionEngine.
Every tool authorization attempt produces a ToolPermissionDecision
that is persisted to the execution trajectory for C6 verification
and C8 Arena evaluation.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from schemas.domain.base import DSRTImmutableSchema, DSRTSchema
from schemas.domain.enums import OrganizationRole, SideEffectClass, ToolRiskLevel


class ToolDenialReason(str, Enum):
    """Exhaustive enumeration of why a tool request was denied (C3 §46)."""

    # Agent-level denials (C3 §12 — agent permission ∩ tool requirement)
    AGENT_NETWORK_NOT_PERMITTED = "AGENT_NETWORK_NOT_PERMITTED"
    AGENT_FILESYSTEM_NOT_PERMITTED = "AGENT_FILESYSTEM_NOT_PERMITTED"
    AGENT_BROWSER_NOT_PERMITTED = "AGENT_BROWSER_NOT_PERMITTED"
    AGENT_EXTERNAL_ACTIONS_NOT_PERMITTED = "AGENT_EXTERNAL_ACTIONS_NOT_PERMITTED"
    AGENT_CREDENTIAL_NOT_PERMITTED = "AGENT_CREDENTIAL_NOT_PERMITTED"

    # Policy-level denials (C3 §12 — org/task/environment policy)
    TOOL_NOT_IN_ALLOWED_LIST = "TOOL_NOT_IN_ALLOWED_LIST"
    TOOL_IN_BLOCKED_LIST = "TOOL_IN_BLOCKED_LIST"
    DOMAIN_BLOCKED = "DOMAIN_BLOCKED"
    DOMAIN_NOT_ALLOWED = "DOMAIN_NOT_ALLOWED"
    FILESYSTEM_WRITE_DENIED = "FILESYSTEM_WRITE_DENIED"
    FILESYSTEM_DELETE_DENIED = "FILESYSTEM_DELETE_DENIED"
    BROWSER_DOWNLOAD_DENIED = "BROWSER_DOWNLOAD_DENIED"
    BROWSER_UPLOAD_DENIED = "BROWSER_UPLOAD_DENIED"
    CREDENTIAL_ACCESS_DENIED = "CREDENTIAL_ACCESS_DENIED"
    EXTERNAL_ACTION_DENIED = "EXTERNAL_ACTION_DENIED"

    # Role/authorization denials (C3 §52)
    INSUFFICIENT_ROLE = "INSUFFICIENT_ROLE"

    # Resource denials (C3 §37)
    TASK_TOOL_LIMIT_EXCEEDED = "TASK_TOOL_LIMIT_EXCEEDED"

    # Environment denials (C3 §36)
    ENVIRONMENT_POLICY_DENIED = "ENVIRONMENT_POLICY_DENIED"

    # Risk/side-effect denials (C3 §14, §48)
    RISK_LEVEL_EXCEEDS_THRESHOLD = "RISK_LEVEL_EXCEEDS_THRESHOLD"
    SIDE_EFFECT_BLOCKED = "SIDE_EFFECT_BLOCKED"


class ToolApprovalRequirement(DSRTImmutableSchema):
    """Describes the approval needed before a tool can execute (C3 §15, §49)."""

    required_role: OrganizationRole = OrganizationRole.MEMBER
    reason: str = Field(default="", max_length=1000)
    risk_level: ToolRiskLevel = ToolRiskLevel.LOW
    side_effect: SideEffectClass = SideEffectClass.READ
    expires_in_seconds: int = Field(default=300, ge=30, le=86400)


class ToolPermissionCheck(DSRTSchema):
    """The complete input to a permission evaluation (C3 §12)."""

    tool_slug: str
    tool_version: str
    tool_risk_level: ToolRiskLevel
    tool_side_effect: SideEffectClass

    # Tool-declared permission requirements
    tool_requires_network: bool = False
    tool_requires_network_outbound: bool = False
    tool_requires_filesystem_read: bool = False
    tool_requires_filesystem_write: bool = False
    tool_requires_filesystem_delete: bool = False
    tool_requires_browser_control: bool = False
    tool_requires_browser_downloads: bool = False
    tool_requires_browser_uploads: bool = False
    tool_requires_credentials: bool = False
    tool_requires_external_actions: bool = False

    # Tool-declared domain restrictions
    tool_allowed_domains: list[str] = Field(default_factory=list)
    tool_blocked_domains: list[str] = Field(default_factory=list)

    # Agent-declared permissions (from AgentManifest)
    agent_network_required: bool = False
    agent_filesystem_access: str = "none"  # "none" | "workspace" | "full"
    agent_browser_access: bool = False
    agent_external_actions_access: bool = False

    # Agent-declared tool lists (from AgentRequirements)
    agent_required_tools: list[str] = Field(default_factory=list)
    agent_optional_tools: list[str] = Field(default_factory=list)

    # Organization policy
    org_allowed_tools: list[str] | None = None
    org_blocked_tools: list[str] | None = None
    org_max_risk_level: ToolRiskLevel | None = None
    org_blocked_side_effects: list[SideEffectClass] | None = None

    # Task policy
    task_allowed_tools: list[str] | None = None
    task_blocked_tools: list[str] | None = None
    task_max_tool_calls: int | None = None
    task_current_tool_calls: int = 0

    # Environment policy
    env_allowed_tools: list[str] | None = None
    env_blocked_tools: list[str] | None = None
    env_network_mode: str = "restricted"

    # User context
    user_role: OrganizationRole | None = None


class ToolPermissionDecision(DSRTImmutableSchema):
    """The immutable, auditable output of a permission evaluation (C3 §52)."""

    tool_slug: str
    tool_version: str
    allowed: bool
    requires_approval: bool = False

    denial_reasons: list[ToolDenialReason] = Field(default_factory=list)
    approval_requirement: ToolApprovalRequirement | None = None

    # Full audit metadata for trajectory persistence
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_denied(self) -> bool:
        return not self.allowed and not self.requires_approval

    @property
    def is_approved_directly(self) -> bool:
        return self.allowed and not self.requires_approval