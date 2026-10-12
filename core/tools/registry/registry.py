"""
Tool Registry Service (C3 §7, §8, §33).

Central service managing tool discovery, version resolution, capability search,
and validation against the DSRT Tool Contract.
"""

from __future__ import annotations

from typing import Any

from core.api.errors.exceptions import ConflictError, NotFoundError, ValidationError
from core.observability.logging import get_logger
from core.repositories.tool_repository import ToolRepository
from core.storage.models.tool import Tool as ToolORM, ToolVersion as ToolVersionORM
from core.tools.errors import ToolNotFoundError, ToolVersionUnavailableError
from schemas.domain.enums import ToolStatus
from schemas.domain.tool import (
    Tool,
    ToolManifest,
    ToolVersion,
)

logger = get_logger("dsrt.tools.registry")


class ToolRegistry:
    """Authoritative catalog for tools in DSRT Core."""

    def __init__(self, tool_repo: ToolRepository) -> None:
        self._repo = tool_repo

    async def register_tool(
        self,
        *,
        manifest: ToolManifest,
        implementation_class: str,
        organization_id: str | None = None,
        make_active: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> ToolVersion:
        """Register a tool package version into the registry."""
        identity = manifest.identity
        slug = identity.slug
        version_str = identity.version

        # 1. Validate contract version
        if identity.contract_version != "1.0":
            raise ValidationError(
                f"Unsupported contract_version '{identity.contract_version}'. Expected '1.0'."
            )

        # 2. Check or create parent Tool entry
        tool_orm = await self._repo.get_by_slug(slug, organization_id=organization_id)
        if not tool_orm:
            tool_orm = await self._repo.create_tool(
                slug=slug,
                name=identity.name,
                category=identity.category,
                publisher=identity.publisher,
                description=manifest.description,
                status=ToolStatus.ACTIVE.value if make_active else ToolStatus.REGISTERED.value,
                organization_id=organization_id,
                metadata_json=metadata or {},
            )
            logger.info("tool_registered", slug=slug, category=identity.category)
        else:
            # Update tool-level metadata/status if requested
            if make_active and tool_orm.status != ToolStatus.ACTIVE.value:
                await self._repo.update_status(tool_orm, ToolStatus.ACTIVE.value)

        # 3. Check for version collision
        existing_version = await self._repo.get_version(tool_orm.id, version_str)
        if existing_version:
            raise ConflictError(
                f"Version '{version_str}' of tool '{slug}' is already registered."
            )

        # 4. Create ToolVersion
        target_status = ToolStatus.ACTIVE.value if make_active else ToolStatus.REGISTERED.value
        version_orm = await self._repo.create_version(
            tool_id=tool_orm.id,
            version=version_str,
            contract_version=identity.contract_version,
            manifest=manifest.model_dump(),
            implementation_class=implementation_class,
            status=target_status,
            metadata_json=metadata or {},
        )

        # 5. Register declared capabilities
        for cap in manifest.capabilities:
            await self._repo.add_capability(
                tool_version_id=version_orm.id,
                capability_slug=cap.slug,
                description=cap.description,
            )

        logger.info(
            "tool_version_registered",
            slug=slug,
            version=version_str,
            status=target_status,
            capabilities_count=len(manifest.capabilities),
        )

        return self._to_version_schema(version_orm)

    async def get_tool(
        self, slug: str, organization_id: str | None = None
    ) -> Tool:
        """Get tool catalog entry by slug."""
        tool_orm = await self._repo.get_by_slug(slug, organization_id=organization_id)
        if not tool_orm:
            raise ToolNotFoundError(f"Tool '{slug}' not found.")
        return self._to_tool_schema(tool_orm)

    async def resolve_tool_version(
        self,
        slug: str,
        version: str | None = None,
        organization_id: str | None = None,
    ) -> ToolVersion:
        """Resolve a specific version of a tool, or default to the active/latest version."""
        tool_orm = await self._repo.get_by_slug(slug, organization_id=organization_id)
        if not tool_orm:
            raise ToolNotFoundError(f"Tool '{slug}' not found.")

        if version is not None:
            version_orm = await self._repo.get_version(tool_orm.id, version)
            if not version_orm:
                raise ToolVersionUnavailableError(
                    f"Version '{version}' of tool '{slug}' not found."
                )
        else:
            # First try active version, then latest
            version_orm = await self._repo.get_active_version(tool_orm.id)
            if not version_orm and tool_orm.latest_version:
                version_orm = await self._repo.get_version(
                    tool_orm.id, tool_orm.latest_version
                )

            if not version_orm:
                raise ToolVersionUnavailableError(
                    f"No active version available for tool '{slug}'."
                )

        return self._to_version_schema(version_orm)

    async def list_tools(
        self,
        *,
        organization_id: str | None = None,
        category: str | None = None,
        status: str | None = None,
    ) -> list[Tool]:
        """List all tools registered in the catalog."""
        tools_orm = await self._repo.list_tools(
            organization_id=organization_id,
            category=category,
            status=status,
        )
        return [self._to_tool_schema(t) for t in tools_orm]

    async def list_tool_versions(self, slug: str) -> list[ToolVersion]:
        """List all versions of a tool."""
        tool_orm = await self._repo.get_by_slug(slug)
        if not tool_orm:
            raise ToolNotFoundError(f"Tool '{slug}' not found.")

        versions_orm = await self._repo.list_versions(tool_orm.id)
        return [self._to_version_schema(v) for v in versions_orm]

    async def discover_tools_for_capabilities(
        self, required_capabilities: list[str]
    ) -> dict[str, list[ToolVersion]]:
        """Find active tools declaring any of the requested capabilities."""
        results: dict[str, list[ToolVersion]] = {}
        for cap in required_capabilities:
            versions_orm = await self._repo.list_by_capability(cap)
            results[cap] = [self._to_version_schema(v) for v in versions_orm]
        return results

    @staticmethod
    def _to_tool_schema(orm: ToolORM) -> Tool:
        return Tool(
            id=orm.id,
            organization_id=orm.organization_id,
            slug=orm.slug,
            name=orm.name,
            category=orm.category,
            publisher=orm.publisher,
            description=orm.description,
            status=ToolStatus(orm.status),
            latest_version=orm.latest_version,
            metadata=orm.metadata_json,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    @staticmethod
    def _to_version_schema(orm: ToolVersionORM) -> ToolVersion:
        manifest_obj = ToolManifest.model_validate(orm.manifest)
        return ToolVersion(
            id=orm.id,
            tool_id=orm.tool_id,
            version=orm.version,
            contract_version=orm.contract_version,
            status=ToolStatus(orm.status),
            manifest=manifest_obj,
            implementation_class=orm.implementation_class,
            metadata=orm.metadata_json,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )