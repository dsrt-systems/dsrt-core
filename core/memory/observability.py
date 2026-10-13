"""
Memory Event Emitter (C4.11).

Emits memory lifecycle events into the execution trajectory so that
C8 Arena can reconstruct memory decisions. Events flow through the
ExecutionKernel's standard emit_event() pipeline.
"""

from __future__ import annotations

from typing import Any

from schemas.domain.enums import EventType

from core.kernel.kernel import ExecutionKernel
from core.observability.logging import get_logger


logger = get_logger("dsrt.memory.observability")


class MemoryEventEmitter:
    """Emits C4 §52 memory lifecycle events into the execution trajectory."""

    def __init__(
        self,
        kernel: ExecutionKernel | None = None,
        execution_id: str | None = None,
    ) -> None:
        self._kernel = kernel
        self._execution_id = execution_id

    async def emit(
        self,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
        *,
        execution_id: str | None = None,
    ) -> None:
        """Emit a memory event. No-op if kernel or execution_id unavailable."""
        eid = execution_id or self._execution_id
        if not self._kernel or not eid:
            logger.debug(
                "memory_event_skipped_no_kernel",
                event_type=event_type.value,
            )
            return

        await self._kernel.emit_event(
            execution_id=eid,
            event_type=event_type,
            source="dsrt.memory",
            payload=payload or {},
        )

    # Convenience helpers for the most common memory events

    async def memory_created(
        self, memory_id: str, memory_type: str, scope: str, importance: str,
        *, execution_id: str | None = None,
    ) -> None:
        await self.emit(
            EventType.MEMORY_CREATED,
            {
                "memory_id": memory_id,
                "memory_type": memory_type,
                "scope": scope,
                "importance": importance,
            },
            execution_id=execution_id,
        )

    async def memory_updated(
        self, memory_id: str, version: int,
        *, execution_id: str | None = None,
    ) -> None:
        await self.emit(
            EventType.MEMORY_UPDATED,
            {"memory_id": memory_id, "version": version},
            execution_id=execution_id,
        )

    async def memory_archived(
        self, memory_id: str,
        *, execution_id: str | None = None,
    ) -> None:
        await self.emit(
            EventType.MEMORY_ARCHIVED,
            {"memory_id": memory_id},
            execution_id=execution_id,
        )

    async def memory_conflict_detected(
        self, memory_a_id: str, memory_b_id: str, description: str,
        *, execution_id: str | None = None,
    ) -> None:
        await self.emit(
            EventType.MEMORY_CONFLICT_DETECTED,
            {
                "memory_a_id": memory_a_id,
                "memory_b_id": memory_b_id,
                "description": description,
            },
            execution_id=execution_id,
        )

    async def memory_deduplicated(
        self, existing_memory_id: str,
        *, execution_id: str | None = None,
    ) -> None:
        await self.emit(
            EventType.MEMORY_DEDUPLICATED,
            {"existing_memory_id": existing_memory_id},
            execution_id=execution_id,
        )

    async def memory_retrieved(
        self, query: str, results_count: int, retrieval_time_ms: int,
        *, execution_id: str | None = None,
    ) -> None:
        await self.emit(
            EventType.MEMORY_RETRIEVED,
            {
                "query": query[:200],
                "results_count": results_count,
                "retrieval_time_ms": retrieval_time_ms,
            },
            execution_id=execution_id,
        )

    async def context_build_started(
        self, execution_id_val: str,
        *, execution_id: str | None = None,
    ) -> None:
        await self.emit(
            EventType.CONTEXT_BUILD_STARTED,
            {"target_execution_id": execution_id_val},
            execution_id=execution_id,
        )

    async def context_build_completed(
        self, total_tokens: int, memories_included: int, build_time_ms: int,
        *, execution_id: str | None = None,
    ) -> None:
        await self.emit(
            EventType.CONTEXT_BUILD_COMPLETED,
            {
                "total_tokens": total_tokens,
                "memories_included": memories_included,
                "build_time_ms": build_time_ms,
            },
            execution_id=execution_id,
        )