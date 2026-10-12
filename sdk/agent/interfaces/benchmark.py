"""
Benchmark SDK Contract (C1 §39-40).

Agents can record benchmark hooks. Full Arena arrives in C8.
"""

from __future__ import annotations

from typing import Any, Protocol


class BenchmarkSDK(Protocol):
    """Benchmark SDK — telemetry hooks for future Arena evaluation."""

    async def record(self, metric: str, value: Any, **tags: Any) -> None:
        """Record a benchmark metric point."""
        ...