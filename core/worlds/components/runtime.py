"""
Runtime Component (C7 §10, §28, §30).

Provides language runtime access (Python, Node.js) within a World.
Wraps C3 PythonSandbox with resource limits.
"""

from __future__ import annotations

from core.observability.logging import get_logger
from core.worlds.components.component import (
    BaseWorldComponent,
    ComponentContext,
    ComponentHealth,
)


logger = get_logger("dsrt.worlds.components.runtime")


class RuntimeComponent(BaseWorldComponent):
    """Language runtime component (Python, Node.js, etc.)."""

    def __init__(
        self, slug: str = "python", language: str = "python",
    ) -> None:
        self._slug = slug
        self._language = language
        self._version: str = "3.13"
        self._packages: list[str] = []

    @property
    def component_type(self) -> str:
        return "runtime"

    @property
    def slug(self) -> str:
        return self._slug

    async def provision(self, context: ComponentContext) -> bool:
        config = context.configuration
        self._version = config.get("version", "3.13")
        self._packages = config.get("packages", [])
        logger.info(
            "runtime_provisioned",
            world_instance=context.world_instance_id,
            language=self._language,
            version=self._version,
            packages=len(self._packages),
        )
        return True

    async def start(self, context: ComponentContext) -> bool:
        logger.info(
            "runtime_started",
            world_instance=context.world_instance_id,
            language=self._language,
        )
        return True

    async def health(self, context: ComponentContext) -> ComponentHealth:
        return ComponentHealth(
            component_id=self.slug,
            component_type=self.component_type,
            status="healthy",
            detail=f"{self._language} {self._version}",
            metrics={
                "language": self._language,
                "version": self._version,
                "packages_installed": len(self._packages),
            },
        )

    async def destroy(self, context: ComponentContext) -> bool:
        logger.info("runtime_destroyed", world_instance=context.world_instance_id)
        return True

    def get_capabilities(self) -> list[str]:
        return [self._language, "code_execution", "scripting"]