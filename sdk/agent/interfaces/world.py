"""
World SDK Contract (C7 §62-63).

Agents interact with their World through this interface.
Actions remain routed through C3 tools — the World SDK provides
observation, state, and resource information only.

Agents must NEVER:
  - Import docker, subprocess, ssh, or VM APIs
  - Access raw infrastructure
  - Bypass the SDK to reach world internals
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SDKWorldInfo:
    """Read-only information about the current world."""
    world_id: str
    world_slug: str
    world_version: str
    status: str
    clock_mode: str = "real_time"
    simulation_date: str | None = None
    capabilities: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SDKWorldObservation:
    """A point-in-time observation of the world state."""
    world_id: str
    timestamp: str
    state: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    component_health: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SDKWorldResources:
    """Current resource usage and limits for the world."""
    cpu_limit: int = 0
    memory_mb_limit: int = 0
    storage_gb_limit: int = 0
    max_processes: int = 0
    max_network_requests: int = 0
    max_browser_sessions: int = 0
    cpu_usage: float = 0.0
    memory_usage_mb: int = 0
    storage_usage_mb: int = 0
    active_processes: int = 0


class WorldSDK(Protocol):
    """World SDK — agent-facing world interaction interface (C7 §62).

    Capabilities:
      - current: Get info about the current world
      - observe: Get a point-in-time observation
      - state: Read the current world state
      - resources: Check resource usage and limits
    """

    async def current(self) -> SDKWorldInfo | None:
        """Get information about the current world instance.

        Returns None if no world is provisioned for this execution.
        """
        ...

    async def observe(self) -> SDKWorldObservation | None:
        """Get a point-in-time observation of the world (C7 §42).

        The observation includes current state, component health,
        and recent events. Filtered through permissions.
        """
        ...

    async def state(self, path: str = "/") -> Any:
        """Read the current world state at the given path.

        Args:
            path: JSON Pointer path into the world state.
                  Default "/" returns the full state.

        Returns:
            The state value at the path, or None.
        """
        ...

    async def resources(self) -> SDKWorldResources:
        """Get current resource usage and limits (C7 §12, §52).

        Returns:
            SDKWorldResources with usage and limit information.
        """
        ...