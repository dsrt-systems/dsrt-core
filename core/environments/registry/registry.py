"""
Environment Registry Service (C3 §33).

Manages registration, versioning, and discovery of environment blueprints.
Mirrors the ToolRegistry pattern from C3.3.
"""

from __future__ import annotations

from typing import Any

from schemas.domain.environment import EnvironmentManifest

from core.api.errors.exceptions import ConflictError, NotFoundError
from core.observability.logging import get_logger
from core.repositories.environment_repository import EnvironmentRepository
from core.storage.models.environment import (
    EnvironmentInstanceORM,
    EnvironmentORM,
    EnvironmentVersionORM,
)


logger = get_logger("dsrt.environments.registry")


class EnvironmentRegistry:
    """Authoritative catalog for environment blueprints in DSRT Core."""

    def __init__(self, env_repo: EnvironmentRepository) -> None:
        self._repo = env_repo

    async def register_environment(
        self,
        *,
        manifest: EnvironmentManifest,
        implementation_class: str,
        make_active: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> EnvironmentVersionORM:
        """Register an environment blueprint version (idempotent per version)."""
        identity = manifest.identity
        slug = identity.slug
        version_str = identity.version

        # Check or create parent Environment entry
        env_orm = await self._repo.get_by_slug(slug)
        if not env_orm:
            env_orm = await self._repo.create_environment(
                slug=slug,
                name=identity.name,
                environment_type=identity.environment_type.value,
                publisher=identity.publisher,
                description=manifest.description,
                metadata_json=metadata or {},
            )
            logger.info("environment_registered", slug=slug)
        else:
            if make_active and env_orm.latest_version != version_str:
                await self._repo.update_environment(
                    env_orm, latest_version=version_str,
                )

        # Check for version collision
        existing_version = await self._repo.get_version(env_orm.id, version_str)
        if existing_version:
            raise ConflictError(
                f"Version '{version_str}' of environment '{slug}' already registered."
            )

        version_orm = await self._repo.create_version(
            environment_id=env_orm.id,
            version=version_str,
            manifest=manifest.model_dump(),
            implementation_class=implementation_class,
            metadata_json=metadata or {},
        )

        if make_active:
            await self._repo.update_environment(
                env_orm, latest_version=version_str,
            )

        logger.info(
            "environment_version_registered",
            slug=slug,
            version=version_str,
        )
        return version_orm

    async def resolve_environment_version(
        self,
        slug: str,
        version: str | None = None,
    ) -> EnvironmentVersionORM:
        """Resolve a specific version of an environment, or the latest."""
        env_orm = await self._repo.get_by_slug(slug)
        if not env_orm:
            raise NotFoundError(f"Environment '{slug}' not found.")

        if version is not None:
            version_orm = await self._repo.get_version(env_orm.id, version)
            if not version_orm:
                raise NotFoundError(
                    f"Version '{version}' of environment '{slug}' not found."
                )
            return version_orm

        # Resolve latest
        if env_orm.latest_version:
            version_orm = await self._repo.get_version(
                env_orm.id, env_orm.latest_version,
            )
            if version_orm:
                return version_orm

        raise NotFoundError(
            f"No active version available for environment '{slug}'."
        )

    async def list_environments(self) -> list[EnvironmentORM]:
        """List all registered environments."""
        return await self._repo.list_environments()