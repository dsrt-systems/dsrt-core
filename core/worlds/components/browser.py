"""
Browser Component (C7 §10, §26).

Provides browser capabilities within a World instance.
Wraps C3 browser tools (web.search, web.retrieve).

In C7 v1, the browser component manages browser session state
and network policy enforcement. Full Playwright/Chromium integration
is deferred to C7 v2.
"""

from __future__ import annotations

from core.observability.logging import get_logger
from core.worlds.components.component import (
    BaseWorldComponent,
    ComponentContext,
    ComponentHealth,
    ComponentSnapshot,
)


logger = get_logger("dsrt.worlds.components.browser")


class BrowserComponent(BaseWorldComponent):
    """Browser component for web interaction within a World."""

    def __init__(self, slug: str = "chromium") -> None:
        self._slug = slug
        self._active_sessions: int = 0
        self._max_sessions: int = 5

    @property
    def component_type(self) -> str:
        return "browser"

    @property
    def slug(self) -> str:
        return self._slug

    async def provision(self, context: ComponentContext) -> bool:
        """Provision browser resources."""
        config = context.configuration
        self._max_sessions = config.get("max_tabs", 5)
        logger.info(
            "browser_provisioned",
            world_instance=context.world_instance_id,
            max_sessions=self._max_sessions,
        )
        return True

    async def start(self, context: ComponentContext) -> bool:
        """Start the browser component."""
        self._active_sessions = 0
        logger.info("browser_started", world_instance=context.world_instance_id)
        return True

    async def health(self, context: ComponentContext) -> ComponentHealth:
        """Check browser health."""
        return ComponentHealth(
            component_id=self.slug,
            component_type=self.component_type,
            status="healthy",
            detail=f"Active sessions: {self._active_sessions}/{self._max_sessions}",
            metrics={
                "active_sessions": self._active_sessions,
                "max_sessions": self._max_sessions,
            },
        )

    async def snapshot(self, context: ComponentContext) -> ComponentSnapshot:
        """Capture browser state (open tabs, cookies reference)."""
        return ComponentSnapshot(
            component_id=self.slug,
            component_type=self.component_type,
            data={
                "active_sessions": self._active_sessions,
                "max_sessions": self._max_sessions,
            },
        )

    async def destroy(self, context: ComponentContext) -> bool:
        """Close all browser sessions and release resources."""
        self._active_sessions = 0
        logger.info("browser_destroyed", world_instance=context.world_instance_id)
        return True

    def get_capabilities(self) -> list[str]:
        return ["browser", "web_browsing", "web_scraping"]