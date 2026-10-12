"""
Event SDK Contract (C1 §24).

Every significant agent action can emit an event into the trajectory.
"""

from __future__ import annotations

from typing import Any, Protocol


class EventSDK(Protocol):
    """Event SDK — trajectory emission."""

    async def emit(
        self, event_type: str, payload: dict[str, Any] | None = None,
    ) -> None:
        """Emit an agent-level domain event into the execution trajectory."""
        ...