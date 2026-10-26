"""Execution lifecycle manager controlling execution trace status transitions."""

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from core.execution.repositories.trace_repository import ExecutionTraceRepository
from schemas.domain.enums import C10ExecutionStatus, ErrorCode


class ExecutionLifecycleManager:
    """Manages formal state transitions and event emission for C10 execution traces."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.trace_repo = ExecutionTraceRepository(session)

    async def transition_to_admitted(self, trace_id: str) -> None:
        await self.trace_repo.update_status(trace_id, C10ExecutionStatus.ADMITTED)

    async def transition_to_running(self, trace_id: str) -> None:
        await self.trace_repo.update_status(trace_id, C10ExecutionStatus.RUNNING)

    async def transition_to_completed(self, trace_id: str) -> None:
        await self.trace_repo.update_status(trace_id, C10ExecutionStatus.SUCCEEDED)

    async def transition_to_failed(
        self, trace_id: str, error_code: str, error_message: str
    ) -> None:
        await self.trace_repo.update_status(
            trace_id,
            C10ExecutionStatus.FAILED,
            error_code=error_code,
            error_message=error_message,
        )

    async def transition_to_cancelled(
        self, trace_id: str, reason: str = "Execution cancelled by user request"
    ) -> None:
        await self.trace_repo.update_status(
            trace_id,
            C10ExecutionStatus.CANCELLED,
            error_code=ErrorCode.C10_EXECUTION_CANCELLED.value,
            error_message=reason,
        )

    async def transition_to_timed_out(self, trace_id: str, timeout_seconds: int) -> None:
        await self.trace_repo.update_status(
            trace_id,
            C10ExecutionStatus.TIMED_OUT,
            error_code=ErrorCode.C10_EXECUTION_TIMEOUT.value,
            error_message=f"Execution timed out after {timeout_seconds} seconds",
        )