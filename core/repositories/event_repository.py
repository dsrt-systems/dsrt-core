"""
ExecutionEvent Repository.

Persists append-only execution events with monotonic sequence numbers per execution.
Events are immutable once written.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.repositories.base import Repository
from core.storage.models import Execution, ExecutionEvent


class EventRepository(Repository):
    async def append_event(
        self,
        *,
        execution_id: str,
        event_type: str,
        source: str,
        payload: dict | None = None,
        request_id: str | None = None,
    ) -> ExecutionEvent:
        """Atomically append an event with a monotonically increasing sequence number."""
        # 1. Fetch current max sequence for execution with row-level locking
        stmt = (
            select(Execution.last_event_sequence)
            .where(Execution.id == execution_id)
            .with_for_update()
        )
        res = await self._session.execute(stmt)
        last_seq = res.scalar_one_or_none()

        if last_seq is None:
            last_seq = 0

        new_seq = last_seq + 1

        # 2. Update sequence counter on execution
        exe_stmt = (
            select(Execution).where(Execution.id == execution_id)
        )
        exe_res = await self._session.execute(exe_stmt)
        execution = exe_res.scalar_one()
        execution.last_event_sequence = new_seq

        # 3. Insert event
        event = ExecutionEvent(
            execution_id=execution_id,
            sequence=new_seq,
            event_type=event_type,
            source=source,
            payload=payload or {},
            request_id=request_id,
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def list_by_execution(
        self,
        execution_id: str,
        *,
        since_sequence: int = 0,
        limit: int = 100,
    ) -> list[ExecutionEvent]:
        """Fetch trajectory events in sequence order."""
        stmt = (
            select(ExecutionEvent)
            .where(
                ExecutionEvent.execution_id == execution_id,
                ExecutionEvent.sequence > since_sequence,
            )
            .order_by(ExecutionEvent.sequence.asc())
            .limit(limit)
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def get_latest_sequence(self, execution_id: str) -> int:
        stmt = select(func.max(ExecutionEvent.sequence)).where(
            ExecutionEvent.execution_id == execution_id
        )
        res = await self._session.execute(stmt)
        val = res.scalar()
        return val if val is not None else 0