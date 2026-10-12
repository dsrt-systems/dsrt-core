"""
Tool Policy Models (C3 §12, §49, §52).

Configuration models for organization, task, and environment-level
tool policies. These are resolved from the database by the engine
and passed as pure data to the intersection logic.
"""

from __future__ import annotations

from pydantic import Field

from schemas.domain.base import DSRTSchema
from schemas.domain.enums import SideEffectClass, ToolRiskLevel


class OrgToolPolicy(DSRTSchema):
    """Organization-wide tool policy (C3 §38)."""

    allowed_tools: list[str] | None = Field(
        default=None,
        description="If set, only these tool slugs are permitted. None = all allowed.",
    )
    blocked_tools: list[str] = Field(
        default_factory=list,
        description="Tool slugs explicitly blocked for this organization.",
    )
    max_risk_level: ToolRiskLevel | None = Field(
        default=None,
        description="Maximum risk level allowed. Tools above this are HARD DENIED.",
    )
    max_risk_without_approval: ToolRiskLevel | None = Field(
        default=None,
        description="Maximum risk level allowed WITHOUT approval. Tools above this REQUIRE approval.",
    )
    blocked_side_effects: list[SideEffectClass] = Field(
        default_factory=list,
        description="Side-effect classes that are completely blocked.",
    )
    requires_approval_for_external: bool = Field(
        default=True,
        description="Whether EXTERNAL_ACTION side-effects require approval.",
    )
    side_effects_requiring_approval: list[SideEffectClass] = Field(
        default_factory=lambda: [
            SideEffectClass.EXTERNAL_ACTION,
            SideEffectClass.IRREVERSIBLE,
        ],
    )


class TaskToolPolicy(DSRTSchema):
    """Per-task tool policy overrides (C3 §12).

    Task policies can only be MORE restrictive than org policies.
    They cannot loosen org-level restrictions.
    """

    allowed_tools: list[str] | None = Field(
        default=None,
        description="If set, only these tools are permitted for this task.",
    )
    blocked_tools: list[str] = Field(
        default_factory=list,
        description="Additional tool slugs blocked for this task.",
    )
    max_tool_calls: int | None = Field(
        default=None,
        description="Maximum number of tool calls for this task.",
    )


class EnvironmentToolPolicy(DSRTSchema):
    """Per-environment tool policy (C3 §36)."""

    allowed_tools: list[str] | None = Field(
        default=None,
        description="If set, only these tools can run in this environment.",
    )
    blocked_tools: list[str] = Field(
        default_factory=list,
        description="Tools blocked in this environment.",
    )
    network_mode: str = Field(
        default="restricted",
        description="Network mode: offline, restricted, controlled, open, proxy.",
    )