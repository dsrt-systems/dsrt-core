"""Startup recovery scanner sweeping orphaned executions after server restarts."""

from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.storage.models.execution_c10 import ExecutionTraceORM
from schemas.domain.enums import C10ExecutionStatus, ErrorCode


class ExecutionStartupScanner:
    """Scans and recovers orphaned executions left in non-terminal state across server restarts."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def recover_orphaned_executions(self) -> int:
        """Finds executions stuck in PENDING or RUNNING state and marks them FAILED."""
        now = datetime.now(timezone.utc)
        stmt = (
            update(ExecutionTraceORM)
            .where(
                ExecutionTraceORM.status.in_(
                    [C10ExecutionStatus.PENDING.value, C10ExecutionStatus.RUNNING.value]
                )
            )
            .values(
                status=C10ExecutionStatus.FAILED.value,
                error_code=ErrorCode.C10_EXECUTION_ORPHANED_ON_RESTART.value,
                error_message="Execution marked failed due to server restart recovery",
                completed_at=now,
                updated_at=now,
            )
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount