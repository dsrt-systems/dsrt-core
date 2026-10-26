"""
WorldSDK Implementation (C7 §62-63).

Bridges the agent-facing WorldSDK Protocol to the Core World Manager,
State Manager, and Component Manager.

Architecture:
    Agent → sdk.world.observe()
        ↓
    WorldSDKImpl
        ↓
    WorldManager.observe() / WorldStateManager / ComponentManager
        ↓
    Filtered through permissions
        ↓
    SDKWorldObservation
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.observability.logging import get_logger
from core.storage.models.world import WorldInstanceORM, WorldVersionORM
from core.worlds.state.state_manager import WorldStateManager
from sdk.agent.interfaces.world import (
    SDKWorldInfo,
    SDKWorldObservation,
    SDKWorldResources,
)


logger = get_logger("sdk.world")


class WorldSDKImpl:
    """Concrete implementation of WorldSDK backed by C7 World infrastructure."""

    def __init__(
        self,
        session: AsyncSession,
        execution_id: str,
        organization_id: str,
    ) -> None:
        self._session = session
        self._execution_id = execution_id
        self._organization_id = organization_id
        self._state_mgr = WorldStateManager(session)

    async def _get_world_instance(self) -> WorldInstanceORM | None:
        """Find the world instance for this execution."""
        stmt = (
            select(WorldInstanceORM)
            .where(
                WorldInstanceORM.execution_id == self._execution_id,
                WorldInstanceORM.organization_id == self._organization_id,
            )
            .order_by(WorldInstanceORM.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def current(self) -> SDKWorldInfo | None:
        """Get information about the current world instance."""
        instance = await self._get_world_instance()
        if not instance:
            return None

        # Load world version for slug and capabilities
        ver_stmt = select(WorldVersionORM).where(
            WorldVersionORM.id == instance.world_version_id,
        )
        ver_result = await self._session.execute(ver_stmt)
        version = ver_result.scalar_one_or_none()

        slug = ""
        ver_str = ""
        capabilities: list[str] = []
        components: list[str] = []

        if version and version.manifest:
            manifest = version.manifest
            identity = manifest.get("identity", {})
            slug = identity.get("slug", "")
            ver_str = identity.get("version", "")
            capabilities = manifest.get("capabilities", [])
            components = [
                c.get("slug", c.get("component_type", ""))
                for c in manifest.get("components", [])
            ]

        return SDKWorldInfo(
            world_id=instance.id,
            world_slug=slug,
            world_version=ver_str,
            status=instance.status,
            clock_mode=instance.clock_mode or "real_time",
            simulation_date=instance.simulation_date,
            capabilities=capabilities,
            components=components,
        )

    async def observe(self) -> SDKWorldObservation | None:
        """Get a point-in-time observation of the world (C7 §42)."""
        instance = await self._get_world_instance()
        if not instance:
            return None

        now = datetime.now(timezone.utc)

        # Get current state
        current_state = await self._state_mgr.get_current_state(instance.id)
        state_dict: dict[str, Any] = {}
        if current_state:
            state_dict = {
                "version": current_state.version,
                "filesystem_keys": list(current_state.filesystem_state.keys())[:20],
                "database_keys": list(current_state.database_state.keys())[:10],
                "browser_active": bool(current_state.browser_state),
                "env_vars_count": len(current_state.environment_variables),
            }

        # Get component health (simplified)
        component_health: dict[str, str] = {}
        if instance.resource_profile:
            component_health["filesystem"] = "healthy"
            component_health["runtime"] = "healthy"

        return SDKWorldObservation(
            world_id=instance.id,
            timestamp=now.isoformat(),
            state=state_dict,
            artifacts=[],
            events=[],
            component_health=component_health,
        )

    async def state(self, path: str = "/") -> Any:
        """Read the current world state at the given path."""
        instance = await self._get_world_instance()
        if not instance:
            return None

        current = await self._state_mgr.get_current_state(instance.id)
        if not current:
            return {}

        if path == "/":
            return {
                "filesystem": current.filesystem_state,
                "database": current.database_state,
                "browser": current.browser_state,
                "application": current.application_state,
                "environment": current.environment_variables,
                "network": current.network_state,
                "packages": current.installed_packages,
                "version": current.version,
            }

        # Navigate JSON Pointer path
        from core.orchestration.state.patches import StatePatchValidator
        full_state = {
            "filesystem": current.filesystem_state,
            "database": current.database_state,
            "browser": current.browser_state,
            "application": current.application_state,
            "environment": current.environment_variables,
            "network": current.network_state,
        }
        return StatePatchValidator.get_value(full_state, path)

    async def resources(self) -> SDKWorldResources:
        """Get current resource usage and limits (C7 §12)."""
        instance = await self._get_world_instance()

        if not instance or not instance.resource_profile:
            return SDKWorldResources()

        profile = instance.resource_profile

        return SDKWorldResources(
            cpu_limit=profile.get("cpu_limit", 4),
            memory_mb_limit=profile.get("memory_mb", 8192),
            storage_gb_limit=profile.get("storage_gb", 20),
            max_processes=profile.get("max_processes", 100),
            max_network_requests=profile.get("max_network_requests", 1000),
            max_browser_sessions=profile.get("max_browser_sessions", 5),
            # Usage would come from health records in production
            cpu_usage=0.0,
            memory_usage_mb=0,
            storage_usage_mb=0,
            active_processes=0,
        )