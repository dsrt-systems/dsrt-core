"""Execution trace repository for persistent database operations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.execution_c10 import (
    ExecutionConfigurationORM,
    ExecutionTraceORM,
)
from schemas.domain.enums import C10ExecutionStatus
from schemas.domain.execution_c10 import ExecutionTraceCreate


class ExecutionTraceRepository:
    """Async repository for managing execution traces in PostgreSQL.

    Domain API keeps stable names (total_cost, total_tokens, duration_ms, total_steps).
    Persistence maps onto live ORM columns
    (total_cost_usd, total_*_tokens, total_duration_ms, step_count).
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_trace(
        self,
        trace_data: ExecutionTraceCreate,
        configuration_id: str,
        pricing_snapshot_id: Optional[str] = None,
    ) -> ExecutionTraceORM:
        trace_id = new_id(IdPrefix.C10_EXECUTION_TRACE)
        now = datetime.now(timezone.utc)

        # Pull required identity fields from the frozen configuration row.
        config = await self.session.get(ExecutionConfigurationORM, configuration_id)
        if config is None:
            raise ValueError(
                f"Execution configuration not found for trace create: {configuration_id}"
            )

        orm = ExecutionTraceORM(
            id=trace_id,
            organization_id=trace_data.organization_id,
            configuration_id=configuration_id,
            agent_slug=config.agent_slug,
            agent_version_id=config.agent_version_id,
            model_fingerprint_id=config.model_fingerprint_id,
            protocol=trace_data.protocol.value
            if hasattr(trace_data.protocol, "value")
            else str(trace_data.protocol),
            mode=trace_data.mode.value
            if hasattr(trace_data.mode, "value")
            else str(trace_data.mode),
            status=C10ExecutionStatus.PENDING.value,
            status_reason=None,
            worker_id=None,
            worker_heartbeat_at=None,
            idempotency_key=None,
            step_count=0,
            total_input_tokens=0,
            total_output_tokens=0,
            total_cached_input_tokens=0,
            total_model_calls=0,
            total_tool_calls=0,
            total_cost_usd=0.0,
            total_duration_ms=0,
            output=None,
            artifact_ids=[],
            error_code=None,
            error_message=None,
            error_metadata={
                "metadata_json": trace_data.metadata_json or {},
                "pricing_snapshot_id": pricing_snapshot_id or config.pricing_snapshot_id,
            },
            attempt=1,
            started_at=None,
            completed_at=None,
            created_at=now,
            updated_at=now,
        )
        self.session.add(orm)
        await self.session.commit()
        await self.session.refresh(orm)
        return orm

    async def get_by_id(self, trace_id: str) -> Optional[ExecutionTraceORM]:
        stmt = select(ExecutionTraceORM).where(ExecutionTraceORM.id == trace_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_status(
        self,
        trace_id: str,
        status: C10ExecutionStatus,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Optional[ExecutionTraceORM]:
        now = datetime.now(timezone.utc)
        status_value = status.value if isinstance(status, C10ExecutionStatus) else str(status)

        values: Dict[str, Any] = {
            "status": status_value,
            "updated_at": now,
        }

        if status == C10ExecutionStatus.RUNNING:
            values["started_at"] = now
        elif status in (
            C10ExecutionStatus.SUCCEEDED,
            C10ExecutionStatus.FAILED,
            C10ExecutionStatus.CANCELLED,
            C10ExecutionStatus.BUDGET_EXCEEDED,
        ):
            values["completed_at"] = now

        if error_code is not None:
            values["error_code"] = error_code
        if error_message is not None:
            values["error_message"] = error_message
            values["status_reason"] = error_message

        stmt = (
            update(ExecutionTraceORM)
            .where(ExecutionTraceORM.id == trace_id)
            .values(**values)
        )
        await self.session.execute(stmt)
        await self.session.commit()
        return await self.get_by_id(trace_id)

    async def update_metrics(
        self,
        trace_id: str,
        total_cost: float,
        total_tokens: int,
        duration_ms: float,
        total_steps: int,
        claims_count: int = 0,
        total_input_tokens: Optional[int] = None,
        total_output_tokens: Optional[int] = None,
        total_model_calls: Optional[int] = None,
        total_tool_calls: Optional[int] = None,
    ) -> Optional[ExecutionTraceORM]:
        now = datetime.now(timezone.utc)

        # Prefer explicit split; otherwise attribute aggregate tokens to output.
        in_tokens = int(total_input_tokens) if total_input_tokens is not None else 0
        out_tokens = (
            int(total_output_tokens)
            if total_output_tokens is not None
            else int(total_tokens)
        )

        values: Dict[str, Any] = {
            "total_cost_usd": float(total_cost),
            "total_input_tokens": in_tokens,
            "total_output_tokens": out_tokens,
            "total_duration_ms": int(round(duration_ms)),
            "step_count": int(total_steps),
            "updated_at": now,
        }
        if total_model_calls is not None:
            values["total_model_calls"] = int(total_model_calls)
        if total_tool_calls is not None:
            values["total_tool_calls"] = int(total_tool_calls)

        # claims_count is derived from execution_claims rows; keep in error_metadata bag
        # until a dedicated counter column exists.
        if claims_count:
            existing = await self.get_by_id(trace_id)
            meta = dict(existing.error_metadata or {}) if existing else {}
            meta["claims_count"] = int(claims_count)
            values["error_metadata"] = meta

        stmt = (
            update(ExecutionTraceORM)
            .where(ExecutionTraceORM.id == trace_id)
            .values(**values)
        )
        await self.session.execute(stmt)
        await self.session.commit()
        return await self.get_by_id(trace_id)