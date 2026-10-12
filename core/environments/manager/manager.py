"""
Environment Manager — Lifecycle Orchestrator (C3 §33-38).

The central service that provisions, starts, monitors, snapshots,
resets, and destroys environment instances. Bridges the Environment
Registry (blueprints) with concrete Environment Runtimes (implementations).

Architecture:
    Tool Execution Engine (C3.6)
        ↓ requests environment for tool
    Environment Manager (C3.10)
        ↓ resolves blueprint via Registry
        ↓ loads runtime implementation
        ↓ provisions instance
        ↓ returns environment_instance_id
    Tool runs within the provisioned environment
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.api.errors.exceptions import NotFoundError
from core.environments.lifecycle import (
    EnvironmentStatus,
    is_terminal_environment_status,
    validate_environment_transition,
)
from core.environments.registry.registry import EnvironmentRegistry
from core.environments.runtime.base import EnvironmentRuntime
from core.environments.runtime.workspace_runtime import WorkspaceEnvironmentRuntime
from core.kernel.fingerprint import content_hash
from core.observability.logging import get_logger
from core.repositories.environment_repository import EnvironmentRepository
from core.storage.models.environment import EnvironmentInstanceORM


logger = get_logger("dsrt.environments.manager")

# Registry of known runtime implementations
_RUNTIME_REGISTRY: dict[str, type] = {
    "FILE": WorkspaceEnvironmentRuntime,
    "PYTHON": WorkspaceEnvironmentRuntime,  # Python uses workspace as parent
    "API": WorkspaceEnvironmentRuntime,     # API tools use workspace for artifacts
}


class EnvironmentManager:
    """Orchestrates the complete environment instance lifecycle."""

    def __init__(
        self,
        session: AsyncSession,
        registry: EnvironmentRegistry | None = None,
    ) -> None:
        self._session = session
        self._repo = EnvironmentRepository(session)
        self._registry = registry or EnvironmentRegistry(self._repo)

    async def provision(
        self,
        *,
        environment_slug: str,
        environment_version: str | None = None,
        organization_id: str,
        task_id: str | None = None,
        execution_id: str | None = None,
        world_instance_id: str | None = None,
        resource_overrides: dict[str, Any] | None = None,
    ) -> EnvironmentInstanceORM:
        """Provision a new environment instance for an execution.

        Full lifecycle:
            1. Resolve environment blueprint from registry
            2. Create instance record (REQUESTED)
            3. Load runtime implementation
            4. Provision runtime (PROVISIONING → READY)
            5. Return provisioned instance
        """
        start_time = time.perf_counter()

        # 1. Resolve blueprint
        env_version = await self._registry.resolve_environment_version(
            environment_slug, environment_version,
        )
        manifest_data = env_version.manifest
        impl_class_str = env_version.implementation_class

        # 2. Build resource/policy profiles from manifest + overrides
        resource_profile = manifest_data.get("resources", {})
        if resource_overrides:
            resource_profile.update(resource_overrides)

        network_policy = manifest_data.get("network", {})
        filesystem_policy = manifest_data.get("filesystem", {})

        # 3. Create instance record
        instance = await self._repo.create_instance(
            environment_version_id=env_version.id,
            environment_type=env_version.environment.environment_type,
            organization_id=organization_id,
            task_id=task_id,
            execution_id=execution_id,
            world_instance_id=world_instance_id,
            status=EnvironmentStatus.REQUESTED.value,
            resource_profile=resource_profile,
            network_policy=network_policy,
            filesystem_policy=filesystem_policy,
        )

        logger.info(
            "environment_instance_created",
            instance_id=instance.id,
            environment_slug=environment_slug,
            status=instance.status,
        )

        # 4. Transition to PROVISIONING
        await self._transition(instance, EnvironmentStatus.PROVISIONING)

        # 5. Load runtime and provision
        try:
            runtime = self._load_runtime(impl_class_str)
            provision_result = await runtime.provision(
                instance_id=instance.id,
                organization_id=organization_id,
                execution_id=execution_id,
                resource_profile=resource_profile,
                network_policy=network_policy,
                filesystem_policy=filesystem_policy,
            )

            workspace_path = provision_result.get("workspace_path")
            runtime_ref = provision_result.get("runtime_reference")

            # 6. Transition to READY
            await self._repo.update_instance(
                instance,
                status=EnvironmentStatus.READY.value,
                workspace_root=workspace_path,
                runtime_reference=runtime_ref,
                started_at=datetime.now(timezone.utc),
            )

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.info(
                "environment_instance_ready",
                instance_id=instance.id,
                duration_ms=duration_ms,
                runtime_reference=runtime_ref,
            )

        except Exception as e:
            await self._repo.update_instance(
                instance,
                status=EnvironmentStatus.FAILED.value,
            )
            logger.error(
                "environment_provision_failed",
                instance_id=instance.id,
                error=str(e),
            )
            raise

        return instance

    async def activate(
        self, instance_id: str,
    ) -> EnvironmentInstanceORM:
        """Mark an environment as ACTIVE (a tool is executing within it)."""
        instance = await self._get_instance(instance_id)
        await self._transition(instance, EnvironmentStatus.ACTIVE)
        await self._repo.update_instance(
            instance, status=EnvironmentStatus.ACTIVE.value,
        )
        return instance

    async def deactivate(
        self, instance_id: str,
    ) -> EnvironmentInstanceORM:
        """Mark an environment as IDLE (tool execution finished)."""
        instance = await self._get_instance(instance_id)
        await self._transition(instance, EnvironmentStatus.IDLE)
        await self._repo.update_instance(
            instance, status=EnvironmentStatus.IDLE.value,
        )
        return instance

    async def snapshot(
        self, instance_id: str, snapshot_type: str = "checkpoint",
    ) -> dict[str, Any]:
        """Capture a snapshot of the environment state."""
        instance = await self._get_instance(instance_id)
        runtime = self._load_runtime_for_instance(instance)

        snap_data = await runtime.snapshot(
            instance_id=instance.id,
            runtime_reference=instance.runtime_reference,
        )

        state_hash = snap_data.get("state_hash", "unknown")
        config_hash = content_hash(
            str(instance.resource_profile) + str(instance.network_policy)
        )

        snapshot_orm = await self._repo.create_snapshot(
            environment_instance_id=instance.id,
            snapshot_type=snapshot_type,
            state_hash=state_hash,
            configuration_hash=config_hash,
            size_bytes=snap_data.get("total_size_bytes", 0),
            metadata=snap_data,
        )

        logger.info(
            "environment_snapshot_created",
            instance_id=instance_id,
            snapshot_id=snapshot_orm.id,
            snapshot_type=snapshot_type,
        )

        return {
            "snapshot_id": snapshot_orm.id,
            "state_hash": state_hash,
            "snapshot_type": snapshot_type,
        }

    async def reset(
        self, instance_id: str,
    ) -> EnvironmentInstanceORM:
        """Reset an environment to its base state."""
        instance = await self._get_instance(instance_id)
        runtime = self._load_runtime_for_instance(instance)

        await runtime.reset(
            instance_id=instance.id,
            runtime_reference=instance.runtime_reference,
        )

        logger.info("environment_instance_reset", instance_id=instance_id)
        return instance

    async def destroy(
        self, instance_id: str,
    ) -> bool:
        """Destroy an environment instance and release all resources."""
        instance = await self._get_instance(instance_id)

        if is_terminal_environment_status(EnvironmentStatus(instance.status)):
            logger.debug(
                "environment_already_terminated",
                instance_id=instance_id,
                status=instance.status,
            )
            return False

        # Transition to TERMINATING
        await self._transition(instance, EnvironmentStatus.TERMINATING)
        await self._repo.update_instance(
            instance, status=EnvironmentStatus.TERMINATING.value,
        )

        # Destroy runtime resources
        try:
            runtime = self._load_runtime_for_instance(instance)
            await runtime.destroy(
                instance_id=instance.id,
                runtime_reference=instance.runtime_reference,
            )
        except Exception as e:
            logger.warning(
                "environment_destroy_runtime_error",
                instance_id=instance_id,
                error=str(e),
            )

        # Transition to TERMINATED
        await self._repo.update_instance(
            instance,
            status=EnvironmentStatus.TERMINATED.value,
            stopped_at=datetime.now(timezone.utc),
            destroyed_at=datetime.now(timezone.utc),
        )

        logger.info("environment_instance_destroyed", instance_id=instance_id)
        return True

    async def health(
        self, instance_id: str,
    ) -> dict[str, Any]:
        """Check health of an environment instance."""
        instance = await self._get_instance(instance_id)
        runtime = self._load_runtime_for_instance(instance)

        runtime_health = await runtime.health(
            instance_id=instance.id,
            runtime_reference=instance.runtime_reference,
        )

        return {
            "instance_id": instance.id,
            "status": instance.status,
            "runtime_health": runtime_health,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_instance(
        self, instance_id: str,
    ) -> EnvironmentInstanceORM:
        instance = await self._repo.get_instance_by_id(instance_id)
        if not instance:
            raise NotFoundError(
                f"Environment instance '{instance_id}' not found."
            )
        return instance

    async def _transition(
        self,
        instance: EnvironmentInstanceORM,
        target: EnvironmentStatus,
    ) -> None:
        current = EnvironmentStatus(instance.status)
        validate_environment_transition(current, target)

    def _load_runtime(self, impl_class_str: str) -> EnvironmentRuntime:
        """Load a runtime implementation by class path or type key."""
        # First check the simple type registry
        type_key = impl_class_str.upper().split(":")[-1].split(".")[-1]
        for key, cls in _RUNTIME_REGISTRY.items():
            if key in type_key or key in impl_class_str.upper():
                return cls()  # type: ignore[return-value]

        # Fallback to workspace runtime
        return WorkspaceEnvironmentRuntime()  # type: ignore[return-value]

    def _load_runtime_for_instance(
        self, instance: EnvironmentInstanceORM,
    ) -> EnvironmentRuntime:
        """Load the appropriate runtime for an existing instance."""
        env_type = instance.environment_type.upper()
        if env_type in _RUNTIME_REGISTRY:
            return _RUNTIME_REGISTRY[env_type]()  # type: ignore[return-value]
        return WorkspaceEnvironmentRuntime()  # type: ignore[return-value]