"""
Memory Permission Policies (C4 §34, §42).

Configurable policies governing who can read, write, promote, and delete
memories at various scopes. These policies are resolved from organization
configuration and agent manifests.
"""

from __future__ import annotations

from pydantic import Field

from schemas.domain.base import DSRTSchema
from schemas.domain.enums import MemoryScope


class MemoryAccessPolicy(DSRTSchema):
    """Per-agent or per-organization memory access rules (C4 §34)."""

    readable_scopes: list[MemoryScope] = Field(
        default_factory=lambda: [
            MemoryScope.EXECUTION,
            MemoryScope.TASK,
            MemoryScope.PROJECT,
        ],
        description="Scopes from which this agent/user can read memories.",
    )
    writable_scopes: list[MemoryScope] = Field(
        default_factory=lambda: [
            MemoryScope.EXECUTION,
            MemoryScope.TASK,
            MemoryScope.PROJECT,
        ],
        description="Scopes to which this agent/user can write memories.",
    )
    promotable_scopes: list[MemoryScope] = Field(
        default_factory=list,
        description="Scopes to which this agent/user can promote memories (e.g. task → project).",
    )
    deletable_scopes: list[MemoryScope] = Field(
        default_factory=list,
        description="Scopes from which this agent/user can delete memories.",
    )


class MemoryScopePolicy(DSRTSchema):
    """Organization-level memory scope configuration (C4 §7, §8)."""

    allow_cross_project_read: bool = Field(
        default=False,
        description="Whether agents can read memories from projects they don't own.",
    )
    allow_cross_task_read: bool = Field(
        default=True,
        description="Whether agents can read memories from other tasks in the same project.",
    )
    require_approval_for_org_write: bool = Field(
        default=True,
        description="Whether writing to organization scope requires admin approval.",
    )
    default_agent_policy: MemoryAccessPolicy = Field(
        default_factory=MemoryAccessPolicy,
        description="Default memory access policy for agents without explicit configuration.",
    )