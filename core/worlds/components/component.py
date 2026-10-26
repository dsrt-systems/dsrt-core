"""
Base World Component Contract (C7 §11).

Every pluggable world component implements this abstract base class.
The ComponentManager orchestrates their lifecycle.

Component Lifecycle (C7 §11):
    provision → start → [running] → snapshot/restore → destroy

Components are stateless configuration holders. Actual state lives
in the C3 tool runtimes they wrap.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ComponentContext:
    """Execution context passed to every component operation."""
    world_instance_id: str
    organization_id: str
    execution_id: str | None = None
    task_id: str | None = None
    workspace_path: str | None = None
    configuration: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ComponentHealth:
    """Health status of a single component."""
    component_id: str
    component_type: str
    status: str = "unknown"  # healthy | degraded | unhealthy | unknown
    detail: str = ""
    last_checked: datetime | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def is_healthy(self) -> bool:
        return self.status == "healthy"


@dataclass
class ComponentSnapshot:
    """Point-in-time snapshot of a component's state."""
    component_id: str
    component_type: str
    data: dict[str, Any] = field(default_factory=dict)
    storage_reference: str | None = None
    size_bytes: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BaseWorldComponent(ABC):
    """Abstract base class for all world components (C7 §11).

    Subclasses wrap specific C3 capabilities:
      - FilesystemComponent → C3 WorkspaceManager
      - BrowserComponent → C3 browser tools
      - TerminalComponent → C3 shell tools
      - RuntimeComponent → C3 PythonSandbox
      - DatabaseComponent → C3 database tools
    """

    @property
    @abstractmethod
    def component_type(self) -> str:
        """The WorldComponentType value (e.g., 'filesystem', 'browser')."""
        ...

    @property
    @abstractmethod
    def slug(self) -> str:
        """Unique identifier within a world (e.g., 'workspace', 'chromium')."""
        ...

    @property
    def version(self) -> str:
        """Component version."""
        return "1.0.0"

    @abstractmethod
    async def provision(self, context: ComponentContext) -> bool:
        """Provision the component's resources.

        Returns True if provisioning succeeded.
        """
        ...

    @abstractmethod
    async def start(self, context: ComponentContext) -> bool:
        """Start the component after provisioning.

        Returns True if the component is now operational.
        """
        ...

    @abstractmethod
    async def health(self, context: ComponentContext) -> ComponentHealth:
        """Check the component's operational health."""
        ...

    async def snapshot(self, context: ComponentContext) -> ComponentSnapshot:
        """Capture the component's current state.

        Default implementation returns an empty snapshot.
        Override for components with meaningful state.
        """
        return ComponentSnapshot(
            component_id=self.slug,
            component_type=self.component_type,
        )

    async def restore(
        self, context: ComponentContext, snapshot: ComponentSnapshot,
    ) -> bool:
        """Restore the component from a snapshot.

        Default implementation is a no-op.
        Override for components with restorable state.
        """
        return True

    @abstractmethod
    async def destroy(self, context: ComponentContext) -> bool:
        """Tear down the component and release resources.

        Returns True if cleanup succeeded.
        """
        ...

    def get_capabilities(self) -> list[str]:
        """Return the capability slugs this component provides.

        Used by the World Registry for capability-based matching.
        """
        return [self.component_type]