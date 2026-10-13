"""
State SDK Contract (C1 §27).

Agents maintain domain-specific state through Core-controlled persistence.
"""

from __future__ import annotations

from typing import Any, Protocol


class StateSDK(Protocol):
    """State SDK — durable agent working state."""

    async def get(self, key: str) -> Any:
        """Retrieve a state value."""
        ...

    async def set(self, key: str, value: Any) -> None:
        """Set a state value."""
        ...

    async def delete(self, key: str) -> None:
        """Delete a state value."""
        ...

    async def merge(self, patch: dict[str, Any]) -> None:
        """Merge a patch into agent state."""
        ...

    async def set_many(self, values: dict[str, Any]) -> None:
        """Set multiple values at once."""
        ...

    async def clear(self) -> None:
        """Clear all state."""
        ...

    async def snapshot(self) -> dict[str, Any]:
        """Capture the current state as a dict."""
        ...