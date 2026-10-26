"""
C10.3 Direct Execution Runtime - Step Runner
Manages execution step states through the ExecutionStepRepository.
"""

from typing import Dict, Any, Callable, Awaitable
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from schemas.domain.enums import StepKind, StepStatus
from core.execution.repositories.step_repository import ExecutionStepRepository

logger = logging.getLogger(__name__)


class StepRunner:
    """Orchestrates individual steps inside an execution trace."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.step_repo = ExecutionStepRepository(session)

    async def run_step(
        self,
        trace_id: str,
        step_number: int,
        kind: StepKind,
        name: str,
        input_data: Dict[str, Any],
        execute_fn: Callable[[], Awaitable[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """
        Executes a pipeline step: CREATE -> RUN -> COMPLETE (with metrics).
        Uses exactly the signatures defined in ExecutionStepRepository.
        """
        # 1. Create Step (Sets status to RUNNING via Repo)
        step_orm = await self.step_repo.create_step(
            trace_id=trace_id,
            step_number=step_number,
            kind=kind,
            name=name,
            input_data=input_data,
        )

        try:
            # 2. Execute Work
            output_data = await execute_fn()

            # 3. Extract Metrics
            usage = output_data.get("usage", {})
            tokens_used = usage.get("total_tokens", 0)
            duration_ms = output_data.get("duration_ms", 0.0)
            cost_usd = round(tokens_used * 0.000002, 6)  # Basic fallback estimation

            # 4. Complete Step
            await self.step_repo.update_step_status(
                step_id=step_orm.id,
                status=StepStatus.SUCCEEDED,
                output_data=output_data,
                duration_ms=duration_ms,
                cost_usd=cost_usd,
                tokens_used=tokens_used,
            )

            return output_data

        except Exception as e:
            logger.error(f"Step {name} failed: {e}", exc_info=True)
            await self.step_repo.update_step_status(
                step_id=step_orm.id,
                status=StepStatus.FAILED,
                error_message=str(e),
            )
            raise e