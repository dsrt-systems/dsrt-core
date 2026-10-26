"""
Component Manager (C7 §10-11, §37).

Orchestrates the lifecycle of all components within a World instance.
Ensures components are provisioned, started, health-checked, and
destroyed in the correct order.

Startup Contract (C7 §37):
    Before an agent enters a World:
      - filesystem healthy
      - browser healthy (if present)
      - database healthy (if present)
      - network policy loaded
      - credentials available
      - resource limits active
      - telemetry active
    Only then: AGENT READY
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.observability.logging import get_logger
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.world_state import WorldComponentORM
from core.worlds.components.component import (
    BaseWorldComponent,
    ComponentContext,
    ComponentHealth,
)
from core.worlds.components.browser import BrowserComponent
from core.worlds.components.database import DatabaseComponent
from core.worlds.components.filesystem import FilesystemComponent
from core.worlds.components.runtime import RuntimeComponent
from core.worlds.components.terminal import TerminalComponent


logger = get_logger("dsrt.worlds.components.manager")

# Registry of built-in component types → classes
_COMPONENT_REGISTRY: dict[str, type[BaseWorldComponent]] = {
    "filesystem": FilesystemComponent,
    "browser": BrowserComponent,
    "terminal": TerminalComponent,
    "runtime": RuntimeComponent,
    "database": DatabaseComponent,
}


class ComponentManager:
    """Manages the lifecycle of all components in a World instance.

    Usage:
        mgr = ComponentManager(session)
        await mgr.provision_all(world_instance_id, component_specs, context)
        health = await mgr.health_check_all(context)
        await mgr.destroy_all(context)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._active_components: dict[str, BaseWorldComponent] = {}

    def create_component(
        self,
        component_type: str,
        slug: str,
        configuration: dict[str, Any] | None = None,
    ) -> BaseWorldComponent:
        """Instantiate a component from the registry."""
        cls = _COMPONENT_REGISTRY.get(component_type)
        if not cls:
            raise ValueError(
                f"Unknown component type '{component_type}'. "
                f"Available: {sorted(_COMPONENT_REGISTRY.keys())}"
            )

        config = configuration or {}

        if component_type == "runtime":
            return cls(slug=slug, language=config.get("language", "python"))
        return cls(slug=slug)

    async def provision_all(
        self,
        world_instance_id: str,
        component_specs: list[dict[str, Any]],
        context: ComponentContext,
    ) -> dict[str, bool]:
        """Provision all components for a world instance.

        Args:
            world_instance_id: The world instance ID.
            component_specs: List of component spec dicts from WorldManifest.
            context: Shared execution context.

        Returns:
            Dict mapping component slug → provision success.
        """
        results: dict[str, bool] = {}

        for spec in component_specs:
            comp_type = spec.get("component_type", "")
            if isinstance(comp_type, str):
                type_str = comp_type
            else:
                type_str = comp_type.value if hasattr(comp_type, "value") else str(comp_type)

            slug = spec.get("slug", type_str)
            config = spec.get("configuration", {})

            try:
                component = self.create_component(type_str, slug, config)
                context.configuration = config

                success = await component.provision(context)
                results[slug] = success

                if success:
                    self._active_components[slug] = component

                    # Persist component record
                    comp_orm = WorldComponentORM(
                        id=new_id(IdPrefix.WORLD_COMPONENT),
                        world_instance_id=world_instance_id,
                        component_type=type_str,
                        slug=slug,
                        version=component.version,
                        status="PROVISIONED" if success else "FAILED",
                        configuration=config,
                        started_at=datetime.now(timezone.utc) if success else None,
                        health_status="healthy" if success else "unhealthy",
                    )
                    self._session.add(comp_orm)

                logger.info(
                    "component_provisioned",
                    component=slug,
                    type=type_str,
                    success=success,
                )

            except Exception as e:
                results[slug] = False
                logger.error(
                    "component_provision_failed",
                    component=slug,
                    error=str(e),
                )

        await self._session.flush()
        return results

    async def start_all(
        self, context: ComponentContext,
    ) -> dict[str, bool]:
        """Start all provisioned components."""
        results: dict[str, bool] = {}
        for slug, component in self._active_components.items():
            try:
                results[slug] = await component.start(context)
            except Exception as e:
                results[slug] = False
                logger.error(
                    "component_start_failed",
                    component=slug,
                    error=str(e),
                )
        return results

    async def health_check_all(
        self, context: ComponentContext,
    ) -> dict[str, ComponentHealth]:
        """Check health of all active components (C7 §37-38)."""
        results: dict[str, ComponentHealth] = {}
        for slug, component in self._active_components.items():
            try:
                results[slug] = await component.health(context)
            except Exception as e:
                results[slug] = ComponentHealth(
                    component_id=slug,
                    component_type=component.component_type,
                    status="unhealthy",
                    detail=str(e),
                )
        return results

    async def is_world_ready(
        self, context: ComponentContext,
    ) -> tuple[bool, list[str]]:
        """Check if all required components are healthy (C7 §37).

        Returns:
            (is_ready, list_of_unhealthy_components)
        """
        health = await self.health_check_all(context)
        unhealthy = [
            slug for slug, h in health.items() if not h.is_healthy
        ]
        return len(unhealthy) == 0, unhealthy

    async def destroy_all(
        self, context: ComponentContext,
    ) -> dict[str, bool]:
        """Destroy all active components and release resources."""
        results: dict[str, bool] = {}
        for slug, component in reversed(list(self._active_components.items())):
            try:
                results[slug] = await component.destroy(context)
            except Exception as e:
                results[slug] = False
                logger.error(
                    "component_destroy_failed",
                    component=slug,
                    error=str(e),
                )
        self._active_components.clear()
        return results

    def get_active_components(self) -> list[str]:
        """Return slugs of all active components."""
        return list(self._active_components.keys())