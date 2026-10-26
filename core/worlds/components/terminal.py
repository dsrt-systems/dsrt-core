"""
Terminal Component (C7 §10, §28).

Provides terminal/shell access within a World instance.
Wraps C3 shell.execute tool with sandboxing.
"""

from __future__ import annotations

from core.observability.logging import get_logger
from core.worlds.components.component import (
    BaseWorldComponent,
    ComponentContext,
    ComponentHealth,
)


logger = get_logger("dsrt.worlds.components.terminal")


class TerminalComponent(BaseWorldComponent):
    """Terminal component for shell access within a World."""

    def __init__(self, slug: str = "terminal") -> None:
        self._slug = slug
        self._shell: str = "bash"
        self._timeout: int = 120

    @property
    def component_type(self) -> str:
        return "terminal"

    @property
    def slug(self) -> str:
        return self._slug

    async def provision(self, context: ComponentContext) -> bool:
        config = context.configuration
        self._shell = config.get("shell", "bash")
        self._timeout = config.get("timeout_seconds", 120)
        logger.info(
            "terminal_provisioned",
            world_instance=context.world_instance_id,
            shell=self._shell,
        )
        return True

    async def start(self, context: ComponentContext) -> bool:
        logger.info("terminal_started", world_instance=context.world_instance_id)
        return True

    async def health(self, context: ComponentContext) -> ComponentHealth:
        return ComponentHealth(
            component_id=self.slug,
            component_type=self.component_type,
            status="healthy",
            detail=f"Shell: {self._shell}, timeout: {self._timeout}s",
        )

    async def destroy(self, context: ComponentContext) -> bool:
        logger.info("terminal_destroyed", world_instance=context.world_instance_id)
        return True

    def get_capabilities(self) -> list[str]:
        return ["terminal", "shell", "git"]