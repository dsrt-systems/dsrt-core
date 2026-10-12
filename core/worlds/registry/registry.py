"""
World Registry Service (C3 §39).

Manages registration, versioning, and discovery of world blueprints.
"""

from __future__ import annotations

from typing import Any

from schemas.domain.world import WorldManifest

from core.api.errors.exceptions import ConflictError, NotFoundError
from core.observability.logging import get_logger
from core.repositories.world_repository import WorldRepository
from core.storage.models.world import WorldORM, WorldVersionORM


logger = get_logger("dsrt.worlds.registry")


class WorldRegistry:
    """Authoritative catalog for world blueprints in DSRT Core."""

    def __init__(self, world_repo: WorldRepository) -> None:
        self._repo = world_repo

    async def register_world(
        self,
        *,
        manifest: WorldManifest,
        implementation_class: str,
        make_active: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> WorldVersionORM:
        """Register a world blueprint version (idempotent per version)."""
        identity = manifest.identity
        slug = identity.slug
        version_str = identity.version

        world_orm = await self._repo.get_by_slug(slug)
        if not world_orm:
            world_orm = await self._repo.create_world(
                slug=slug,
                name=identity.name,
                publisher=identity.publisher,
                description=manifest.description,
                metadata_json=metadata or {},
            )
            logger.info("world_registered", slug=slug)

        existing_version = await self._repo.get_version(world_orm.id, version_str)
        if existing_version:
            raise ConflictError(
                f"Version '{version_str}' of world '{slug}' already registered."
            )

        version_orm = await self._repo.create_version(
            world_id=world_orm.id,
            version=version_str,
            manifest=manifest.model_dump(),
            implementation_class=implementation_class,
            metadata_json=metadata or {},
        )

        if make_active:
            await self._repo.update_world(world_orm, latest_version=version_str)

        logger.info(
            "world_version_registered",
            slug=slug,
            version=version_str,
        )
        return version_orm

    async def resolve_world_version(
        self,
        slug: str,
        version: str | None = None,
    ) -> WorldVersionORM:
        """Resolve a specific version of a world, or the latest."""
        world_orm = await self._repo.get_by_slug(slug)
        if not world_orm:
            raise NotFoundError(f"World '{slug}' not found.")

        if version is not None:
            version_orm = await self._repo.get_version(world_orm.id, version)
            if not version_orm:
                raise NotFoundError(
                    f"Version '{version}' of world '{slug}' not found."
                )
            return version_orm

        if world_orm.latest_version:
            version_orm = await self._repo.get_version(
                world_orm.id, world_orm.latest_version,
            )
            if version_orm:
                return version_orm

        raise NotFoundError(
            f"No active version available for world '{slug}'."
        )

    async def list_worlds(self) -> list[WorldORM]:
        """List all registered worlds."""
        return await self._repo.list_worlds()