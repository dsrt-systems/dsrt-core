"""
Environment Runtime Protocol (C3 §33).

Every environment type (workspace, container, browser, etc.) must
implement this protocol to be managed by the EnvironmentManager.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EnvironmentRuntime(Protocol):
    """Protocol for environment runtime implementations."""

    runtime_type: str

    async def provision(
        self,
        instance_id: str,
        organization_id: str,
        execution_id: str | None,
        resource_profile: dict[str, Any],
        network_policy: dict[str, Any],
        filesystem_policy: dict[str, Any],
    ) -> dict[str, Any]:
        """Provision the environment. Returns runtime-specific metadata."""
        ...

    async def start(
        self,
        instance_id: str,
        runtime_reference: str | None = None,
    ) -> None:
        """Start the environment (make it ready for tool execution)."""
        ...

    async def health(
        self,
        instance_id: str,
        runtime_reference: str | None = None,
    ) -> dict[str, Any]:
        """Return health status of the environment."""
        ...

    async def snapshot(
        self,
        instance_id: str,
        runtime_reference: str | None = None,
    ) -> dict[str, Any]:
        """Capture a point-in-time snapshot. Returns snapshot metadata."""
        ...

    async def reset(
        self,
        instance_id: str,
        runtime_reference: str | None = None,
    ) -> None:
        """Reset the environment to its base state."""
        ...

    async def destroy(
        self,
        instance_id: str,
        runtime_reference: str | None = None,
    ) -> None:
        """Destroy the environment and release all resources."""
        ...