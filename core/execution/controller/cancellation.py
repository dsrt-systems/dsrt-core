"""In-memory active execution cancellation registry."""

import asyncio
from typing import Dict, Optional


class ExecutionCancellationRegistry:
    """Tracks active asyncio task handles for live executions to support cancellation."""

    _instance: Optional["ExecutionCancellationRegistry"] = None

    def __init__(self) -> None:
        self._tasks: Dict[str, asyncio.Task] = {}

    @classmethod
    def get_instance(cls) -> "ExecutionCancellationRegistry":
        if cls._instance is None:
            cls._instance = ExecutionCancellationRegistry()
        return cls._instance

    def register(self, trace_id: str, task: asyncio.Task) -> None:
        self._tasks[trace_id] = task

    def unregister(self, trace_id: str) -> None:
        self._tasks.pop(trace_id, None)

    def cancel(self, trace_id: str) -> bool:
        task = self._tasks.get(trace_id)
        if task and not task.done():
            task.cancel()
            self.unregister(trace_id)
            return True
        return False

    def is_active(self, trace_id: str) -> bool:
        task = self._tasks.get(trace_id)
        return task is not None and not task.done()