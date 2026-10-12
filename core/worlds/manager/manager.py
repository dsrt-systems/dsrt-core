"""
World Manager — Lifecycle Orchestrator (C3 §39-40).

Provisions, resets, and destroys world instances. A world instance
composes one or more environment instances under a unified policy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.api.errors.exceptions import NotFoundError
from core.environments.manager.manager import EnvironmentManager
from core.kernel.fingerprint import content_hash
from core.observability.logging import get_logger
from core.repositories.environment_repository import EnvironmentRepository
from core.repositories.world_repository import WorldRepository
from core.worlds.registry.registry import WorldRegistry
from core.storage.models.world import WorldInstanceORM


logger = get_logger("dsrt.worlds.manager")


class WorldManager:
    """Orchestrates world instance lifecycle."""

    def __init__(
        self,
        session: AsyncSession,
        world_registry: WorldRegistry | None = None,
        env_manager: EnvironmentManager | None = None,
    ) -> None:
        self._session = session
        self._world_repo = WorldRepository(session)
        self._world_registry = world_registry or WorldRegistry(self._world_repo)
        self._env_manager = env_manager or EnvironmentManager(session)

    async def provision(
        self,
        *,
        world_slug: str,
        world_version: str | None = None,
        organization_id: str,
        task_id: str | None = None,
        execution_id: str | None = None,
        policy_overrides: dict[str, Any] | None = None,
    ) -> WorldInstanceORM:
        """Provision a new world instance for an execution."""
        # 1. Resolve world blueprint
        world_ver = await self._world_registry.resolve_world_version(
            world_slug, world_version,
        )
        manifest = world_ver.manifest

        # 2. Build effective policy
        policy = manifest.get("policy", {})
        if policy_overrides:
            policy.update(policy_overrides)

        # 3. Compute configuration hash
        config_hash = content_hash(str(manifest) + str(policy))

        # 4. Create world instance record
        instance = await self._world_repo.create_instance(
            world_version_id=world_ver.id,
            organization_id=organization_id,
            task_id=task_id,
            execution_id=execution_id,
            status="PROVISIONING",
            policy=policy,
            configuration_hash=config_hash,
        )

        # 5. Provision required environments
        env_slugs = manifest.get("required_environments", [])
        for env_slug in env_slugs:
            try:
                await self._env_manager.provision(
                    environment_slug=env_slug,
                    organization_id=organization_id,
                    task_id=task_id,
                    execution_id=execution_id,
                    world_instance_id=instance.id,
                )
            except Exception as e:
                logger.warning(
                    "world_env_provision_failed",
                    world_slug=world_slug,
                    env_slug=env_slug,
                    error=str(e),
                )

        # 6. Transition to READY
        await self._world_repo.update_instance(
            instance,
            status="READY",
            started_at=datetime.now(timezone.utc),
        )

        logger.info(
            "world_instance_provisioned",
            instance_id=instance.id,
            world_slug=world_slug,
            environments_count=len(env_slugs),
        )

        return instance

    async def reset(self, instance_id: str) -> WorldInstanceORM:
        """Reset a world instance to its base state."""
        instance = await self._world_repo.get_instance_by_id(instance_id)
        if not instance:
            raise NotFoundError(f"World instance '{instance_id}' not found.")

        await self._world_repo.update_instance(instance, status="RESETTING")

        # Reset is a placeholder in C3 — full implementation in C7
        await self._world_repo.update_instance(instance, status="READY")

        logger.info("world_instance_reset", instance_id=instance_id)
        return instance

    async def destroy(self, instance_id: str) -> bool:
        """Destroy a world instance and release all resources."""
        instance = await self._world_repo.get_instance_by_id(instance_id)
        if not instance:
            return False

        if instance.status in ("DESTROYED", "FAILED"):
            return False

        await self._world_repo.update_instance(
            instance,
            status="DESTROYED",
            stopped_at=datetime.now(timezone.utc),
            destroyed_at=datetime.now(timezone.utc),
        )

        logger.info("world_instance_destroyed", instance_id=instance_id)
        return True

    async def get_instance(self, instance_id: str) -> WorldInstanceORM:
        """Get a world instance by ID."""
        instance = await self._world_repo.get_instance_by_id(instance_id)
        if not instance:
            raise NotFoundError(f"World instance '{instance_id}' not found.")
        return instance