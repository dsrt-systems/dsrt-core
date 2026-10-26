"""
C10.3 Direct Execution Runtime - Core Engine
Coordinates context, adapters, and steps to fulfill a DIRECT protocol trace.
"""

from typing import Dict, Any
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from schemas.domain.execution_c10 import ExecutionConfigurationCreate, ExecutionTrace
from schemas.domain.enums import C10ExecutionStatus, StepKind
from core.execution.repositories.trace_repository import ExecutionTraceRepository
from core.execution.direct.context_binder import DirectContextBinder
from core.execution.direct.adapter import DirectExecutionAdapter
from core.execution.direct.step_runner import StepRunner

logger = logging.getLogger(__name__)


class DirectRuntime:
    """Pipeline engine for DIRECT execution."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.trace_repo = ExecutionTraceRepository(session)
        self.step_runner = StepRunner(session)
        self.binder = DirectContextBinder()
        self.adapter = DirectExecutionAdapter()

    async def execute_trace(
        self,
        trace_id: str,
        config: ExecutionConfigurationCreate,
        input_payload: Dict[str, Any],
    ) -> ExecutionTrace:
        """
        Full lifecycle of a Direct Trace execution.
        """
        try:
            # Step 1: Context Binding
            async def bind_fn():
                bound = self.binder.bind(trace_id, config, input_payload)
                return bound.model_dump()

            context_dict = await self.step_runner.run_step(
                trace_id=trace_id,
                step_number=1,
                kind=StepKind.CONTEXT_BUILD,
                name="bind_execution_context",
                input_data=input_payload,
                execute_fn=bind_fn,
            )

            bound_context = self.binder.bind(trace_id, config, input_payload)

            # Step 2: Model Invocation
            async def invoke_fn():
                return await self.adapter.invoke_model(bound_context)

            model_output = await self.step_runner.run_step(
                trace_id=trace_id,
                step_number=2,
                kind=StepKind.MODEL_CALL,
                name="direct_model_invocation",
                input_data={"prompt": bound_context.prompt},
                execute_fn=invoke_fn,
            )

            # Aggregate Metrics
            tokens_used = model_output.get("usage", {}).get("total_tokens", 0)
            duration_ms = model_output.get("duration_ms", 0.0)
            cost_usd = round(tokens_used * 0.000002, 6)

            # Update trace with terminal success metrics
            await self.trace_repo.update_metrics(
                trace_id=trace_id,
                total_cost=cost_usd,
                total_tokens=tokens_used,
                duration_ms=duration_ms,
                total_steps=2,
                claims_count=0,
            )

            updated_orm = await self.trace_repo.update_status(
                trace_id=trace_id,
                status=C10ExecutionStatus.SUCCEEDED,
            )

            return ExecutionTrace.model_validate(updated_orm, from_attributes=True)

        except Exception as e:
            logger.error(f"DirectRuntime failed for trace {trace_id}: {e}", exc_info=True)
            updated_orm = await self.trace_repo.update_status(
                trace_id=trace_id,
                status=C10ExecutionStatus.FAILED,
                error_message=str(e),
            )
            return ExecutionTrace.model_validate(updated_orm, from_attributes=True)