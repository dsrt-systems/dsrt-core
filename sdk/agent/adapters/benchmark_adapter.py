"""
BenchmarkSDK Implementation (C1 §39-40).

Emits structured BENCHMARK_RECORD events into the execution trajectory.
This allows C8 Arena to consume agent-defined metrics.
"""

from __future__ import annotations

from typing import Any

from core.kernel.kernel import ExecutionKernel
from schemas.domain.enums import EventType


class BenchmarkSDKImpl:
    """Concrete implementation of BenchmarkSDK."""

    def __init__(
        self, kernel: ExecutionKernel, execution_id: str, agent_slug: str,
    ) -> None:
        self._kernel = kernel
        self._execution_id = execution_id
        self._agent_slug = agent_slug

    async def record(self, metric: str, value: Any, **tags: Any) -> None:
        """Emit a benchmark metric into the execution trajectory."""
        payload = {
            "metric": metric,
            "value": value,
            "tags": tags,
        }
        await self._kernel.emit_event(
            execution_id=self._execution_id,
            event_type=EventType.BENCHMARK_RECORD,
            source=f"agent.{self._agent_slug}.benchmark",
            payload=payload,
        )