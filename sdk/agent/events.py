"""
Event SDK Interface for Agents (C1 §24).

Allows agents to emit domain events safely via the Core SDK.
"""

from __future__ import annotations

from typing import Any, Protocol


class EventSDK(Protocol):
    """Event SDK interface exposed to agents."""

    async def emit(
        self, event_type: str, payload: dict[str, Any] | None = None,
    ) -> None:
        """Emit an agent-level domain event into the trajectory stream."""
        ...