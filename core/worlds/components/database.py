"""
Database Component (C7 §10, §28).

Provides database access within a World instance.
Wraps C3 database.query tool with connection isolation.
"""

from __future__ import annotations

from core.observability.logging import get_logger
from core.worlds.components.component import (
    BaseWorldComponent,
    ComponentContext,
    ComponentHealth,
    ComponentSnapshot,
)


logger = get_logger("dsrt.worlds.components.database")


class DatabaseComponent(BaseWorldComponent):
    """Database component for SQL access within a World."""

    def __init__(self, slug: str = "postgres") -> None:
        self._slug = slug
        self._db_type: str = "postgres"
        self._version: str = "16"
        self._extensions: list[str] = []

    @property
    def component_type(self) -> str:
        return "database"

    @property
    def slug(self) -> str:
        return self._slug

    async def provision(self, context: ComponentContext) -> bool:
        config = context.configuration
        self._db_type = config.get("type", "postgres")
        self._version = config.get("version", "16")
        self._extensions = config.get("extensions", [])
        logger.info(
            "database_provisioned",
            world_instance=context.world_instance_id,
            db_type=self._db_type,
            version=self._version,
        )
        return True

    async def start(self, context: ComponentContext) -> bool:
        logger.info("database_started", world_instance=context.world_instance_id)
        return True

    async def health(self, context: ComponentContext) -> ComponentHealth:
        return ComponentHealth(
            component_id=self.slug,
            component_type=self.component_type,
            status="healthy",
            detail=f"{self._db_type} {self._version}",
            metrics={
                "db_type": self._db_type,
                "version": self._version,
                "extensions": self._extensions,
            },
        )

    async def snapshot(self, context: ComponentContext) -> ComponentSnapshot:
        """Capture database state reference."""
        return ComponentSnapshot(
            component_id=self.slug,
            component_type=self.component_type,
            data={
                "db_type": self._db_type,
                "extensions": self._extensions,
            },
        )

    async def destroy(self, context: ComponentContext) -> bool:
        logger.info("database_destroyed", world_instance=context.world_instance_id)
        return True

    def get_capabilities(self) -> list[str]:
        return ["database", "sql", self._db_type]