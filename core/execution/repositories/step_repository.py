"""Execution step repository for persistent step management."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.execution_c10 import ExecutionStepORM
from schemas.domain.enums import StepKind, StepStatus


class ExecutionStepRepository:
    """Async repository for execution step lifecycle records.

    Domain API uses schema names (trace_id, step_number, input_data, tokens_used).
    Persistence maps those onto the live ORM columns
    (execution_trace_id, step_index, inputs_ref, input/output_tokens).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_step(
        self,
        trace_id: str,
        step_number: int,
        kind: StepKind,
        name: str,
        input_data: Dict[str, Any],
        description: Optional[str] = None,
        parent_step_id: Optional[str] = None,
    ) -> ExecutionStepORM:
        step_id = new_id(IdPrefix.C10_EXECUTION_STEP)
        now = datetime.now(timezone.utc)

        orm = ExecutionStepORM(
            id=step_id,
            execution_trace_id=trace_id,
            step_index=step_number,
            parent_step_id=parent_step_id,
            kind=kind.value if isinstance(kind, StepKind) else str(kind),
            status=StepStatus.RUNNING.value,
            name=name,
            description=description,
            input_tokens=0,
            output_tokens=0,
            cached_input_tokens=0,
            cost_usd=0.0,
            duration_ms=0,
            inputs_ref=input_data or {},
            outputs_ref=None,
            error_code=None,
            error_message=None,
            started_at=now,
            completed_at=None,
            created_at=now,
            updated_at=now,
        )
        self.session.add(orm)
        await self.session.commit()
        await self.session.refresh(orm)
        return orm

    async def update_step_status(
        self,
        step_id: str,
        status: StepStatus,
        output_data: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        error_code: Optional[str] = None,
        duration_ms: Optional[float] = None,
        cost_usd: Optional[float] = None,
        tokens_used: Optional[int] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
    ) -> Optional[ExecutionStepORM]:
        now = datetime.now(timezone.utc)
        values: Dict[str, Any] = {
            "status": status.value if isinstance(status, StepStatus) else str(status),
            "updated_at": now,
        }

        if status in (
            StepStatus.SUCCEEDED,
            StepStatus.FAILED,
            StepStatus.SKIPPED,
            StepStatus.CANCELLED,
        ):
            values["completed_at"] = now

        if output_data is not None:
            values["outputs_ref"] = output_data
        if error_message is not None:
            values["error_message"] = error_message
        if error_code is not None:
            values["error_code"] = error_code
        if duration_ms is not None:
            values["duration_ms"] = int(round(duration_ms))
        if cost_usd is not None:
            values["cost_usd"] = float(cost_usd)

        # Prefer explicit split; fall back to tokens_used as output_tokens.
        if input_tokens is not None:
            values["input_tokens"] = int(input_tokens)
        if output_tokens is not None:
            values["output_tokens"] = int(output_tokens)
        elif tokens_used is not None:
            values["output_tokens"] = int(tokens_used)

        stmt = (
            update(ExecutionStepORM)
            .where(ExecutionStepORM.id == step_id)
            .values(**values)
        )
        await self.session.execute(stmt)
        await self.session.commit()
        return await self.get_by_id(step_id)

    async def get_by_id(self, step_id: str) -> Optional[ExecutionStepORM]:
        stmt = select(ExecutionStepORM).where(ExecutionStepORM.id == step_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_trace(self, trace_id: str) -> List[ExecutionStepORM]:
        stmt = (
            select(ExecutionStepORM)
            .where(ExecutionStepORM.execution_trace_id == trace_id)
            .order_by(ExecutionStepORM.step_index.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())