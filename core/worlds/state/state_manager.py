"""
World State Manager (C7 §15-16).

Manages versioned world state. Every agent action that mutates the
world creates a new state version, enabling replay, debugging,
verification, rollback, and evaluation.

Key principle (C7 §15):
    World state ≠ Agent state. They are separate and must not merge.

    WORLD STATE:
      filesystem, database, browser session, application state,
      environment variables, network state, installed packages

    AGENT STATE:
      reasoning state, domain findings, plan state, workflow
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import EventType, WorldChangeType, WorldActionReversibility

from core.kernel.kernel import ExecutionKernel
from core.observability.logging import get_logger
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.world_state import (
    WorldStateChangeORM,
    WorldStateVersionORM,
)


logger = get_logger("dsrt.worlds.state")


class WorldStateManager:
    """Manages versioned world state for a World instance (C7 §15-16).

    Usage:
        mgr = WorldStateManager(session, kernel)
        version = await mgr.record_mutation(
            world_instance_id="wi_1",
            change_type="FILE_CREATED",
            component="filesystem",
            target="/workspace/output/report.md",
            after_state={"size": 82000},
            triggered_by="research_agent",
        )
        state = await mgr.get_current_state("wi_1")
        history = await mgr.get_state_history("wi_1")
    """

    def __init__(
        self,
        session: AsyncSession,
        kernel: ExecutionKernel | None = None,
    ) -> None:
        self._session = session
        self._kernel = kernel

    async def get_current_version(
        self, world_instance_id: str,
    ) -> int:
        """Get the latest state version number for a world instance."""
        stmt = select(func.max(WorldStateVersionORM.version)).where(
            WorldStateVersionORM.world_instance_id == world_instance_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def get_current_state(
        self, world_instance_id: str,
    ) -> WorldStateVersionORM | None:
        """Get the latest state version record."""
        stmt = (
            select(WorldStateVersionORM)
            .where(
                WorldStateVersionORM.world_instance_id == world_instance_id,
            )
            .order_by(WorldStateVersionORM.version.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_state_at_version(
        self, world_instance_id: str, version: int,
    ) -> WorldStateVersionORM | None:
        """Get a specific state version (for replay/debugging)."""
        stmt = select(WorldStateVersionORM).where(
            WorldStateVersionORM.world_instance_id == world_instance_id,
            WorldStateVersionORM.version == version,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def record_mutation(
        self,
        *,
        world_instance_id: str,
        change_type: str,
        component: str,
        target: str,
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
        triggered_by: str | None = None,
        node_execution_id: str | None = None,
        reversibility: str = WorldActionReversibility.REVERSIBLE.value,
        metadata: dict[str, Any] | None = None,
    ) -> WorldStateVersionORM:
        """Record a world state mutation (C7 §16, §46).

        Creates a new state version and a change record.

        Args:
            world_instance_id: The world being mutated.
            change_type: WorldChangeType value (FILE_CREATED, etc.)
            component: Which component was affected.
            target: What was affected (file path, table, URL, etc.)
            before_state: State before the mutation.
            after_state: State after the mutation.
            triggered_by: Agent slug or system component.
            node_execution_id: C5 node that triggered this.
            reversibility: REVERSIBLE, PARTIALLY_REVERSIBLE, IRREVERSIBLE.
            metadata: Additional context.

        Returns:
            The new WorldStateVersionORM.
        """
        # 1. Get current state to build the new version
        current = await self.get_current_state(world_instance_id)
        new_version = (current.version + 1) if current else 1

        # 2. Build new state by merging the mutation into current state
        new_fs = dict(current.filesystem_state if current else {})
        new_db = dict(current.database_state if current else {})
        new_browser = dict(current.browser_state if current else {})
        new_app = dict(current.application_state if current else {})
        new_env = dict(current.environment_variables if current else {})
        new_net = dict(current.network_state if current else {})
        new_pkgs = list(current.installed_packages if current else [])

        # Apply mutation to the appropriate state dimension
        if component == "filesystem":
            new_fs[target] = after_state or {"change": change_type}
        elif component == "database":
            new_db[target] = after_state or {"change": change_type}
        elif component == "browser":
            new_browser[target] = after_state or {"change": change_type}
        elif component in ("runtime", "application"):
            new_app[target] = after_state or {"change": change_type}
        elif component == "network":
            new_net[target] = after_state or {"change": change_type}

        # 3. Create new state version
        state_version = WorldStateVersionORM(
            id=new_id(IdPrefix.WORLD_STATE),
            world_instance_id=world_instance_id,
            version=new_version,
            filesystem_state=new_fs,
            database_state=new_db,
            browser_state=new_browser,
            application_state=new_app,
            environment_variables=new_env,
            network_state=new_net,
            installed_packages=new_pkgs,
            triggered_by=triggered_by,
        )
        self._session.add(state_version)

        # 4. Create change record
        change = WorldStateChangeORM(
            id=new_id(IdPrefix.WORLD_CHANGE),
            world_instance_id=world_instance_id,
            state_version_id=state_version.id,
            node_execution_id=node_execution_id,
            change_type=change_type,
            component=component,
            target=target,
            before_reference=before_state,
            after_reference=after_state,
            reversibility=reversibility,
            metadata_json=metadata or {},
        )
        self._session.add(change)
        await self._session.flush()

        # 5. Emit event
        if self._kernel:
            # Find execution_id from the world instance
            try:
                from core.storage.models.world import WorldInstanceORM
                wi_stmt = select(WorldInstanceORM.execution_id).where(
                    WorldInstanceORM.id == world_instance_id,
                )
                wi_result = await self._session.execute(wi_stmt)
                exe_id = wi_result.scalar_one_or_none()
                if exe_id:
                    await self._kernel.emit_event(
                        execution_id=exe_id,
                        event_type=EventType.WORLD_STATE_CHANGED,
                        source="dsrt.worlds.state",
                        payload={
                            "world_instance_id": world_instance_id,
                            "version": new_version,
                            "change_type": change_type,
                            "component": component,
                            "target": target,
                            "triggered_by": triggered_by,
                        },
                    )
            except Exception as e:
                logger.warning("state_event_emission_failed", error=str(e))

        logger.info(
            "world_state_mutation_recorded",
            world_instance=world_instance_id,
            version=new_version,
            change_type=change_type,
            component=component,
            target=target,
        )

        return state_version

    async def get_state_history(
        self,
        world_instance_id: str,
        limit: int = 50,
    ) -> list[WorldStateVersionORM]:
        """Get the state version history for a world instance."""
        stmt = (
            select(WorldStateVersionORM)
            .where(
                WorldStateVersionORM.world_instance_id == world_instance_id,
            )
            .order_by(WorldStateVersionORM.version.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_changes_for_version(
        self,
        state_version_id: str,
    ) -> list[WorldStateChangeORM]:
        """Get all changes that produced a specific state version."""
        stmt = (
            select(WorldStateChangeORM)
            .where(WorldStateChangeORM.state_version_id == state_version_id)
            .order_by(WorldStateChangeORM.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_all_changes(
        self,
        world_instance_id: str,
        component: str | None = None,
        limit: int = 200,
    ) -> list[WorldStateChangeORM]:
        """Get all state changes for a world instance."""
        stmt = (
            select(WorldStateChangeORM)
            .where(
                WorldStateChangeORM.world_instance_id == world_instance_id,
            )
        )
        if component:
            stmt = stmt.where(WorldStateChangeORM.component == component)
        stmt = stmt.order_by(WorldStateChangeORM.created_at.asc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_mutation_summary(
        self,
        world_instance_id: str,
    ) -> dict[str, Any]:
        """Get a summary of all mutations for a world instance."""
        current_version = await self.get_current_version(world_instance_id)

        # Count changes by type
        from sqlalchemy import select as sa_select
        type_stmt = (
            sa_select(
                WorldStateChangeORM.change_type,
                func.count(WorldStateChangeORM.id),
            )
            .where(
                WorldStateChangeORM.world_instance_id == world_instance_id,
            )
            .group_by(WorldStateChangeORM.change_type)
        )
        type_result = await self._session.execute(type_stmt)
        by_type = {row[0]: row[1] for row in type_result.all()}

        # Count changes by component
        comp_stmt = (
            sa_select(
                WorldStateChangeORM.component,
                func.count(WorldStateChangeORM.id),
            )
            .where(
                WorldStateChangeORM.world_instance_id == world_instance_id,
            )
            .group_by(WorldStateChangeORM.component)
        )
        comp_result = await self._session.execute(comp_stmt)
        by_component = {row[0]: row[1] for row in comp_result.all()}

        # Count irreversible actions
        irr_stmt = sa_select(func.count(WorldStateChangeORM.id)).where(
            WorldStateChangeORM.world_instance_id == world_instance_id,
            WorldStateChangeORM.reversibility == WorldActionReversibility.IRREVERSIBLE.value,
        )
        irr_result = await self._session.execute(irr_stmt)
        irreversible_count = irr_result.scalar() or 0

        return {
            "world_instance_id": world_instance_id,
            "current_version": current_version,
            "total_changes": sum(by_type.values()),
            "by_change_type": by_type,
            "by_component": by_component,
            "irreversible_actions": irreversible_count,
        }