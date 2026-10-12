"""
Tool Repository.

Handles database operations for tools, tool versions, and tool capabilities.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from core.repositories.base import Repository
from core.storage.models.tool import Tool, ToolCapabilityORM, ToolVersion


class ToolRepository(Repository):
    """Repository managing tools, versions, and capabilities."""

    async def create_tool(
        self,
        *,
        slug: str,
        name: str,
        category: str,
        publisher: str = "dsrt",
        description: str = "",
        status: str = "REGISTERED",
        organization_id: str | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> Tool:
        """Create a new tool entry in the registry."""
        tool = Tool(
            slug=slug,
            name=name,
            category=category,
            publisher=publisher,
            description=description,
            status=status,
            organization_id=organization_id,
            metadata_json=metadata_json or {},
        )
        self._session.add(tool)
        await self._session.flush()
        return tool

    async def get_by_id(self, tool_id: str) -> Tool | None:
        """Get a tool by its primary key ID."""
        stmt = (
            select(Tool)
            .where(Tool.id == tool_id)
            .options(selectinload(Tool.versions))
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_slug(
        self, slug: str, organization_id: str | None = None
    ) -> Tool | None:
        """Get a tool by its unique slug, filtering by organization or system-wide."""
        stmt = (
            select(Tool)
            .where(Tool.slug == slug)
            .options(selectinload(Tool.versions))
        )
        if organization_id is not None:
            stmt = stmt.where(
                or_(
                    Tool.organization_id == organization_id,
                    Tool.organization_id.is_(None),
                )
            )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_tools(
        self,
        *,
        organization_id: str | None = None,
        category: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[Tool]:
        """List registered tools matching filter criteria."""
        stmt = select(Tool).options(selectinload(Tool.versions))

        if organization_id is not None:
            stmt = stmt.where(
                or_(
                    Tool.organization_id == organization_id,
                    Tool.organization_id.is_(None),
                )
            )
        else:
            stmt = stmt.where(Tool.organization_id.is_(None))

        if category is not None:
            stmt = stmt.where(Tool.category == category)
        if status is not None:
            stmt = stmt.where(Tool.status == status)

        stmt = stmt.order_by(Tool.created_at.desc()).limit(limit)
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def create_version(
        self,
        *,
        tool_id: str,
        version: str,
        contract_version: str,
        manifest: dict[str, Any],
        implementation_class: str,
        status: str = "REGISTERED",
        metadata_json: dict[str, Any] | None = None,
    ) -> ToolVersion:
        """Create a new version for a registered tool."""
        tool_version = ToolVersion(
            tool_id=tool_id,
            version=version,
            contract_version=contract_version,
            status=status,
            manifest=manifest,
            implementation_class=implementation_class,
            metadata_json=metadata_json or {},
        )
        self._session.add(tool_version)
        await self._session.flush()

        # Update latest_version on parent tool
        tool = await self.get_by_id(tool_id)
        if tool:
            tool.latest_version = version
            await self._session.flush()

        return tool_version

    async def get_version_by_id(self, version_id: str) -> ToolVersion | None:
        """Get a specific tool version by primary key."""
        stmt = (
            select(ToolVersion)
            .where(ToolVersion.id == version_id)
            .options(
                selectinload(ToolVersion.tool),
                selectinload(ToolVersion.capabilities),
            )
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_version(
        self, tool_id: str, version: str
    ) -> ToolVersion | None:
        """Get a specific version of a tool."""
        stmt = (
            select(ToolVersion)
            .where(
                ToolVersion.tool_id == tool_id,
                ToolVersion.version == version,
            )
            .options(
                selectinload(ToolVersion.tool),
                selectinload(ToolVersion.capabilities),
            )
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_active_version(self, tool_id: str) -> ToolVersion | None:
        """Get the active version of a tool."""
        stmt = (
            select(ToolVersion)
            .where(
                ToolVersion.tool_id == tool_id,
                ToolVersion.status == "ACTIVE",
            )
            .order_by(ToolVersion.created_at.desc())
            .options(
                selectinload(ToolVersion.tool),
                selectinload(ToolVersion.capabilities),
            )
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_versions(self, tool_id: str) -> list[ToolVersion]:
        """List all versions of a tool in creation order."""
        stmt = (
            select(ToolVersion)
            .where(ToolVersion.tool_id == tool_id)
            .order_by(ToolVersion.created_at.desc())
            .options(selectinload(ToolVersion.capabilities))
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def add_capability(
        self,
        *,
        tool_version_id: str,
        capability_slug: str,
        description: str = "",
    ) -> ToolCapabilityORM:
        """Link a capability to a tool version."""
        capability = ToolCapabilityORM(
            tool_version_id=tool_version_id,
            capability_slug=capability_slug,
            description=description,
        )
        self._session.add(capability)
        await self._session.flush()
        return capability

    async def list_by_capability(
        self, capability_slug: str
    ) -> list[ToolVersion]:
        """Find all active tool versions that declare a given capability."""
        stmt = (
            select(ToolVersion)
            .join(ToolCapabilityORM)
            .where(
                ToolCapabilityORM.capability_slug == capability_slug,
                ToolVersion.status == "ACTIVE",
            )
            .options(
                selectinload(ToolVersion.tool),
                selectinload(ToolVersion.capabilities),
            )
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def update_status(self, tool: Tool, status: str) -> Tool:
        """Update the lifecycle status of a tool."""
        tool.status = status
        await self._session.flush()
        return tool

    async def update_version_status(
        self, tool_version: ToolVersion, status: str
    ) -> ToolVersion:
        """Update the status of a specific tool version."""
        tool_version.status = status
        await self._session.flush()
        return tool_version