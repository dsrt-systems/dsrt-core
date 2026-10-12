"""
StateSDK Implementation.

In-process state store scoped to a single execution.
C4 replaces this with the durable Memory & State Fabric.
"""

from __future__ import annotations

from typing import Any


class StateSDKImpl:
    """Concrete implementation of StateSDK — process-local for C1."""

    def __init__(self) -> None:
        self._state: dict[str, Any] = {}

    async def get(self, key: str) -> Any:
        return self._state.get(key)

    async def set(self, key: str, value: Any) -> None:
        self._state[key] = value

    async def merge(self, patch: dict[str, Any]) -> None:
        self._state.update(patch)

    async def snapshot(self) -> dict[str, Any]:
        return dict(self._state)