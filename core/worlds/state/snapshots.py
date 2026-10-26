"""
World Snapshot Manager (C7 §17-19).

Creates, restores, and manages world snapshots for:
  - Base snapshots (clean starting environment)
  - Checkpoint snapshots (mid-execution state)
  - Evaluation snapshots (known benchmark state)

Snapshots enable:
  - Deterministic reset (C7 §19)
  - Crash recovery (C7 §70)
  - Benchmark reproducibility (C7 §20)
  - C6 verification (C7 §44)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import EventType, WorldSnapshotType

from core.kernel.fingerprint import content_hash
from core.kernel.kernel import ExecutionKernel
from core.observability.logging import get_logger
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.world import WorldInstanceORM
from core.storage.models.world_state import (
    WorldSnapshotORM,
    WorldStateVersionORM,
)
from core.worlds.state.state_manager import WorldStateManager


logger = get_logger("dsrt.worlds.snapshots")


class WorldSnapshotManager:
    """Manages world snapshots for reproducibility and recovery (C7 §17-19).

    Usage:
        mgr = WorldSnapshotManager(session, kernel)
        snapshot = await mgr.create_snapshot(
            world_instance_id="wi_1",
            snapshot_type="checkpoint",
            label="After research phase",
        )
        await mgr.restore_snapshot(snapshot.id)
    """

    def __init__(
        self,
        session: AsyncSession,
        kernel: ExecutionKernel | None = None,
    ) -> None:
        self._session = session
        self._kernel = kernel
        self._state_mgr = WorldStateManager(session, kernel)

    async def create_snapshot(
        self,
        world_instance_id: str,
        snapshot_type: str = WorldSnapshotType.CHECKPOINT.value,
        label: str = "",
    ) -> WorldSnapshotORM:
        """Create a snapshot of the current world state (C7 §17).

        Captures:
          - Current state version
          - All component states
          - Configuration hash
          - State hash for integrity verification

        Args:
            world_instance_id: The world to snapshot.
            snapshot_type: "base", "checkpoint", or "evaluation".
            label: Human-readable description.

        Returns:
            The persisted WorldSnapshotORM.
        """
        # 1. Get current state
        current_state = await self._state_mgr.get_current_state(
            world_instance_id,
        )

        # 2. Compute state hash
        state_data = ""
        if current_state:
            state_data = str({
                "fs": current_state.filesystem_state,
                "db": current_state.database_state,
                "browser": current_state.browser_state,
                "app": current_state.application_state,
                "env": current_state.environment_variables,
                "net": current_state.network_state,
                "pkgs": current_state.installed_packages,
                "version": current_state.version,
            })
        state_hash = content_hash(state_data)

        # 3. Get world instance for config hash
        wi_stmt = select(WorldInstanceORM).where(
            WorldInstanceORM.id == world_instance_id,
        )
        wi_result = await self._session.execute(wi_stmt)
        instance = wi_result.scalar_one_or_none()
        config_hash = instance.configuration_hash if instance else ""

        # 4. Create snapshot record
        snapshot = WorldSnapshotORM(
            id=new_id(IdPrefix.WORLD_SNAPSHOT_EXT),
            world_instance_id=world_instance_id,
            snapshot_type=snapshot_type,
            state_hash=state_hash,
            configuration_hash=config_hash,
            size_bytes=len(state_data.encode("utf-8")) if state_data else 0,
            filesystem_ref=(
                f"state://{world_instance_id}/v{current_state.version}/fs"
                if current_state else None
            ),
            database_ref=(
                f"state://{world_instance_id}/v{current_state.version}/db"
                if current_state and current_state.database_state else None
            ),
            application_state_ref=(
                f"state://{world_instance_id}/v{current_state.version}/app"
                if current_state and current_state.application_state else None
            ),
            metadata_json={
                "label": label,
                "state_version": current_state.version if current_state else 0,
                "created_by": "snapshot_manager",
            },
        )
        self._session.add(snapshot)
        await self._session.flush()

        # 5. Emit event
        if instance and instance.execution_id:
            await self._emit_event(
                instance.execution_id,
                EventType.WORLD_SNAPSHOT_COMPLETED,
                {
                    "world_instance_id": world_instance_id,
                    "snapshot_id": snapshot.id,
                    "snapshot_type": snapshot_type,
                    "state_version": current_state.version if current_state else 0,
                    "state_hash": state_hash[:16],
                },
            )

        logger.info(
            "world_snapshot_created",
            snapshot_id=snapshot.id,
            world_instance=world_instance_id,
            type=snapshot_type,
            state_version=current_state.version if current_state else 0,
        )

        return snapshot

    async def restore_snapshot(
        self,
        snapshot_id: str,
    ) -> WorldStateVersionORM | None:
        """Restore a world to a previous snapshot (C7 §19).

        Creates a new state version that matches the snapshot's state.
        The original state history is preserved (append-only).

        Args:
            snapshot_id: The snapshot to restore.

        Returns:
            The new state version created by the restore, or None.
        """
        # 1. Load snapshot
        snapshot = await self.get_snapshot(snapshot_id)
        if not snapshot:
            logger.error("snapshot_not_found", snapshot_id=snapshot_id)
            return None

        # 2. Get the state version referenced by the snapshot
        state_version = snapshot.metadata_json.get("state_version", 0)
        if state_version == 0:
            logger.warning(
                "snapshot_has_no_state_version",
                snapshot_id=snapshot_id,
            )
            return None

        original_state = await self._state_mgr.get_state_at_version(
            snapshot.world_instance_id, state_version,
        )
        if not original_state:
            logger.error(
                "snapshot_state_version_not_found",
                snapshot_id=snapshot_id,
                state_version=state_version,
            )
            return None

        # 3. Create a new state version that copies the snapshot state
        current_version = await self._state_mgr.get_current_version(
            snapshot.world_instance_id,
        )
        new_version = current_version + 1

        restored_state = WorldStateVersionORM(
            id=new_id(IdPrefix.WORLD_STATE),
            world_instance_id=snapshot.world_instance_id,
            version=new_version,
            filesystem_state=dict(original_state.filesystem_state),
            database_state=dict(original_state.database_state),
            browser_state=dict(original_state.browser_state),
            application_state=dict(original_state.application_state),
            environment_variables=dict(original_state.environment_variables),
            network_state=dict(original_state.network_state),
            installed_packages=list(original_state.installed_packages),
            triggered_by=f"snapshot_restore:{snapshot_id}",
        )
        self._session.add(restored_state)
        await self._session.flush()

        logger.info(
            "world_snapshot_restored",
            snapshot_id=snapshot_id,
            world_instance=snapshot.world_instance_id,
            restored_from_version=state_version,
            new_version=new_version,
        )

        return restored_state

    async def get_snapshot(
        self, snapshot_id: str,
    ) -> WorldSnapshotORM | None:
        """Get a snapshot by ID."""
        stmt = select(WorldSnapshotORM).where(
            WorldSnapshotORM.id == snapshot_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_snapshots(
        self,
        world_instance_id: str,
        snapshot_type: str | None = None,
        limit: int = 20,
    ) -> list[WorldSnapshotORM]:
        """List snapshots for a world instance."""
        stmt = (
            select(WorldSnapshotORM)
            .where(
                WorldSnapshotORM.world_instance_id == world_instance_id,
            )
        )
        if snapshot_type:
            stmt = stmt.where(
                WorldSnapshotORM.snapshot_type == snapshot_type,
            )
        stmt = stmt.order_by(
            WorldSnapshotORM.created_at.desc(),
        ).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_base_snapshot(
        self, world_instance_id: str,
    ) -> WorldSnapshotORM | None:
        """Get the base (initial) snapshot for a world instance."""
        snapshots = await self.list_snapshots(
            world_instance_id,
            snapshot_type=WorldSnapshotType.BASE.value,
            limit=1,
        )
        return snapshots[0] if snapshots else None

    async def create_base_snapshot(
        self, world_instance_id: str,
    ) -> WorldSnapshotORM:
        """Create the initial base snapshot for a world (C7 §18).

        Should be called immediately after provisioning, before
        any agent actions modify the world.
        """
        return await self.create_snapshot(
            world_instance_id=world_instance_id,
            snapshot_type=WorldSnapshotType.BASE.value,
            label="Initial base state after provisioning",
        )

    # ------------------------------------------------------------------
    # Helpers
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
                source="dsrt.worlds.snapshots",
                payload=payload,
            )
        except Exception as e:
            logger.warning("snapshot_event_failed", error=str(e))