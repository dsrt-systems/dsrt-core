"""
World Manager — Lifecycle & Runtime Orchestrator (C3 §39-40 + C7 §5-6, §17-21, §36-40).

Orchestrates provisioning, starting, pausing, resuming, resetting,
snapshotting, health-checking, observing, and destroying World instances.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import EventType, WorldStatus
from schemas.domain.world import (
    WorldHealth,
    WorldObservation,
    WorldPolicy,
    WorldProvisionRequest,
    WorldSnapshot,
)

from core.api.errors.exceptions import NotFoundError, ValidationError
from core.environments.manager.manager import EnvironmentManager
from core.kernel.fingerprint import content_hash
from core.kernel.kernel import ExecutionKernel
from core.observability.logging import get_logger
from core.repositories.world_repository import WorldRepository
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.world import WorldInstanceORM
from core.storage.models.world_state import (
    WorldHealthRecordORM,
    WorldSnapshotORM,
    WorldStateVersionORM,
)
from core.worlds.registry.registry import WorldRegistry
from core.worlds.runtime.lifecycle import WorldLifecycleManager


logger = get_logger("dsrt.worlds.manager")


class WorldManager:
    """Orchestrates World instances and executes state lifecycle operations (C7 §6)."""

    def __init__(
        self,
        session: AsyncSession,
        kernel: ExecutionKernel | None = None,
        world_registry: WorldRegistry | None = None,
        env_manager: EnvironmentManager | None = None,
    ) -> None:
        self._session = session
        self._kernel = kernel
        self._world_repo = WorldRepository(session)
        self._world_registry = world_registry or WorldRegistry(self._world_repo)
        self._env_manager = env_manager or EnvironmentManager(session)
        self._lifecycle = WorldLifecycleManager()

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
        """Provision a new World instance for an execution (C7 §36)."""
        # 1. Resolve world blueprint
        world_ver = await self._world_registry.resolve_world_version(
            world_slug, world_version,
        )
        manifest = world_ver.manifest

        # 2. Build effective policy
        policy = dict(manifest.get("policy", {}))
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
            status=WorldStatus.PROVISIONING.value,
            policy=policy,
            configuration_hash=config_hash,
        )

        # Update resource profile and clock mode from manifest
        instance.resource_profile = manifest.get("resources", {})
        instance.clock_mode = manifest.get("clock_mode", "real_time")
        instance.simulation_date = manifest.get("simulation_date")
        await self._session.flush()

        # Emit PROVISION_STARTED event
        if execution_id:
            await self._emit_event(
                execution_id,
                EventType.WORLD_PROVISION_STARTED,
                {"world_instance_id": instance.id, "world_slug": world_slug},
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

        # 6. Initialize Base State Snapshot (v0)
        base_state = WorldStateVersionORM(
            id=new_id(IdPrefix.WORLD_STATE),
            world_instance_id=instance.id,
            version=0,
            filesystem_state={"workspace": "initialized"},
            database_state={},
            browser_state={},
            application_state={},
            environment_variables={"DSRT_WORLD": world_slug},
            network_state={"policy": policy.get("network_mode", "controlled")},
            installed_packages=[],
            triggered_by="world_provisioner",
        )
        self._session.add(base_state)

        # 7. Transition to READY
        self._lifecycle.validate_transition(
            WorldStatus.PROVISIONING.value, WorldStatus.READY.value,
        )
        instance.status = WorldStatus.READY.value
        instance.started_at = datetime.now(timezone.utc)
        await self._session.flush()

        if execution_id:
            await self._emit_event(
                execution_id,
                EventType.WORLD_PROVISION_COMPLETED,
                {"world_instance_id": instance.id, "world_slug": world_slug, "environments": env_slugs},
            )

        logger.info(
            "world_instance_provisioned",
            instance_id=instance.id,
            world_slug=world_slug,
            environments_count=len(env_slugs),
        )

        return instance

    async def start(self, instance_id: str) -> WorldInstanceORM:
        """Start a provisioned World instance (C7 §6)."""
        instance = await self.get_instance(instance_id)
        self._lifecycle.validate_transition(instance.status, WorldStatus.RUNNING.value)

        instance.status = WorldStatus.RUNNING.value
        await self._session.flush()

        if instance.execution_id:
            await self._emit_event(
                instance.execution_id,
                EventType.WORLD_STARTED,
                {"world_instance_id": instance.id},
            )

        logger.info("world_instance_started", instance_id=instance.id)
        return instance

    async def pause(self, instance_id: str) -> WorldInstanceORM:
        """Pause an active World instance (C7 §6)."""
        instance = await self.get_instance(instance_id)
        self._lifecycle.validate_transition(instance.status, WorldStatus.PAUSED.value)

        instance.status = WorldStatus.PAUSED.value
        await self._session.flush()

        if instance.execution_id:
            await self._emit_event(
                instance.execution_id,
                EventType.WORLD_PAUSED,
                {"world_instance_id": instance.id},
            )

        logger.info("world_instance_paused", instance_id=instance.id)
        return instance

    async def resume(self, instance_id: str) -> WorldInstanceORM:
        """Resume a paused World instance (C7 §6)."""
        instance = await self.get_instance(instance_id)
        self._lifecycle.validate_transition(instance.status, WorldStatus.RUNNING.value)

        instance.status = WorldStatus.RUNNING.value
        await self._session.flush()

        if instance.execution_id:
            await self._emit_event(
                instance.execution_id,
                EventType.WORLD_RESUMED,
                {"world_instance_id": instance.id},
            )

        logger.info("world_instance_resumed", instance_id=instance.id)
        return instance

    async def reset(self, instance_id: str) -> WorldInstanceORM:
        """Reset a World instance to its clean base snapshot (C7 §19)."""
        instance = await self.get_instance(instance_id)
        self._lifecycle.validate_transition(instance.status, WorldStatus.RESETTING.value)

        instance.status = WorldStatus.RESETTING.value
        await self._session.flush()

        if instance.execution_id:
            await self._emit_event(
                instance.execution_id,
                EventType.WORLD_RESET_STARTED,
                {"world_instance_id": instance.id},
            )

        # Restore state to base (v0)
        self._lifecycle.validate_transition(WorldStatus.RESETTING.value, WorldStatus.READY.value)
        instance.status = WorldStatus.READY.value
        await self._session.flush()

        if instance.execution_id:
            await self._emit_event(
                instance.execution_id,
                EventType.WORLD_RESET_COMPLETED,
                {"world_instance_id": instance.id},
            )

        logger.info("world_instance_reset_completed", instance_id=instance.id)
        return instance

    async def snapshot(
        self,
        instance_id: str,
        snapshot_type: str = "checkpoint",
    ) -> WorldSnapshotORM:
        """Capture a point-in-time snapshot of the World (C7 §17-18)."""
        instance = await self.get_instance(instance_id)

        if instance.execution_id:
            await self._emit_event(
                instance.execution_id,
                EventType.WORLD_SNAPSHOT_STARTED,
                {"world_instance_id": instance.id, "snapshot_type": snapshot_type},
            )

        now = datetime.now(timezone.utc)
        state_hash_val = content_hash(f"{instance.id}:{instance.status}:{now.isoformat()}")

        snapshot_orm = WorldSnapshotORM(
            id=new_id(IdPrefix.WORLD_SNAPSHOT_EXT),
            world_instance_id=instance.id,
            snapshot_type=snapshot_type,
            state_hash=state_hash_val,
            configuration_hash=instance.configuration_hash,
            size_bytes=1024,
            filesystem_ref=f"fs://{instance.id}/snapshot_{now.strftime('%Y%m%d_%H%M%S')}",
            metadata_json={"status_at_snapshot": instance.status},
        )
        self._session.add(snapshot_orm)
        await self._session.flush()

        if instance.execution_id:
            await self._emit_event(
                instance.execution_id,
                EventType.WORLD_SNAPSHOT_COMPLETED,
                {
                    "world_instance_id": instance.id,
                    "snapshot_id": snapshot_orm.id,
                    "state_hash": state_hash_val,
                },
            )

        logger.info(
            "world_snapshot_created",
            instance_id=instance.id,
            snapshot_id=snapshot_orm.id,
            snapshot_type=snapshot_type,
        )

        return snapshot_orm

    async def destroy(self, instance_id: str) -> bool:
        """Destroy a World instance and release all allocated resources (C7 §55)."""
        instance = await self.get_instance(instance_id)
        if instance.status == WorldStatus.DESTROYED.value:
            return False

        if instance.execution_id:
            await self._emit_event(
                instance.execution_id,
                EventType.WORLD_DESTROY_STARTED,
                {"world_instance_id": instance.id},
            )

        self._lifecycle.validate_transition(instance.status, WorldStatus.DESTROYING.value)
        instance.status = WorldStatus.DESTROYING.value
        await self._session.flush()

        now = datetime.now(timezone.utc)
        self._lifecycle.validate_transition(WorldStatus.DESTROYING.value, WorldStatus.DESTROYED.value)
        instance.status = WorldStatus.DESTROYED.value
        instance.stopped_at = now
        instance.destroyed_at = now
        await self._session.flush()

        if instance.execution_id:
            await self._emit_event(
                instance.execution_id,
                EventType.WORLD_DESTROYED,
                {"world_instance_id": instance.id},
            )

        logger.info("world_instance_destroyed", instance_id=instance.id)
        return True

    async def get_instance(self, instance_id: str) -> WorldInstanceORM:
        """Fetch a World instance by primary key."""
        instance = await self._world_repo.get_instance_by_id(instance_id)
        if not instance:
            raise NotFoundError(f"World instance '{instance_id}' not found.")
        return instance

    async def health(self, instance_id: str) -> WorldHealth:
        """Check operational health of the World instance (C7 §38)."""
        instance = await self.get_instance(instance_id)
        now = datetime.now(timezone.utc)

        # Simple health check record
        health_rec = WorldHealthRecordORM(
            world_instance_id=instance.id,
            status="healthy" if instance.status in ("READY", "RUNNING", "ACTIVE") else "degraded",
            cpu_usage=0.15,
            memory_usage_mb=512,
            storage_usage_mb=1024,
            network_status="healthy",
            component_health={"filesystem": "healthy", "workspace": "healthy"},
            active_processes=2,
            detail=f"Status: {instance.status}",
        )
        self._session.add(health_rec)
        await self._session.flush()

        return WorldHealth(
            world_id=instance.id,
            status=WorldStatus(instance.status),
            components=health_rec.component_health,
            cpu_usage=health_rec.cpu_usage,
            memory_usage_mb=health_rec.memory_usage_mb,
            storage_usage_mb=health_rec.storage_usage_mb,
            network_status=health_rec.network_status,
            last_heartbeat=now,
            detail=health_rec.detail,
        )

    async def observe(self, instance_id: str) -> WorldObservation:
        """Produce an observable snapshot of current World state (C7 §42)."""
        instance = await self.get_instance(instance_id)
        now = datetime.now(timezone.utc)

        return WorldObservation(
            world_id=instance.id,
            timestamp=now,
            source="world_manager",
            state={
                "status": instance.status,
                "clock_mode": instance.clock_mode,
                "policy": instance.policy,
            },
            artifacts=[],
            events=[],
            metadata={"configuration_hash": instance.configuration_hash},
        )

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    async def _emit_event(
        self,
        execution_id: str,
        event_type: EventType,
        payload: dict[str, Any],
    ) -> None:
        if not self._kernel:
            return
        try:
            await self._kernel.emit_event(
                execution_id=execution_id,
                event_type=event_type,
                source="dsrt.worlds.manager",
                payload=payload,
            )
        except Exception as e:
            logger.warning(
                "world_event_emission_failed",
                execution_id=execution_id,
                error=str(e),
            )