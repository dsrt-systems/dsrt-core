"""
C10.4 Amplification Runtime - Main Engine
The facade wrapping the AmplifiedPipeline for protocol execution.
"""

from typing import Dict, Any
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from schemas.domain.execution_c10 import ExecutionConfigurationCreate, ExecutionTrace
from schemas.domain.enums import C10ExecutionStatus, AmplificationStrategy
from core.execution.repositories.trace_repository import ExecutionTraceRepository
from core.execution.amplified.pipeline import AmplifiedPipeline

logger = logging.getLogger(__name__)


class AmplifiedRuntime:
    """Entry point for handling AMPLIFIED mode execution traces."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.trace_repo = ExecutionTraceRepository(session)
        self.pipeline = AmplifiedPipeline(session)

    async def execute_trace(
        self,
        trace_id: str,
        config: ExecutionConfigurationCreate,
        input_payload: Dict[str, Any],
    ) -> ExecutionTrace:
        """Executes a trace using the Amplification pipeline."""
        try:
            # Map configuration strings to AmplificationStrategy enums
            strategies = []
            for s in config.amplification_strategies:
                if isinstance(s, str):
                    try:
                        strategies.append(AmplificationStrategy(s))
                    except ValueError:
                        logger.warning(f"Ignoring unknown strategy: {s}")
                elif isinstance(s, AmplificationStrategy):
                    strategies.append(s)

            # Execute the unified pipeline
            result = await self.pipeline.execute_pipeline(
                trace_id=trace_id,
                strategies=strategies,
                payload=input_payload
            )

            metrics = result.get("metrics", {})
            tokens = metrics.get("total_tokens", 0)
            duration = metrics.get("duration_ms", 0.0)
            steps = metrics.get("steps_executed", 0)
            cost_usd = round(tokens * 0.000002, 6)

            # Update trace with final terminal metrics
            await self.trace_repo.update_metrics(
                trace_id=trace_id,
                total_cost=cost_usd,
                total_tokens=tokens,
                duration_ms=duration,
                total_steps=steps,
                claims_count=0
            )

            updated_orm = await self.trace_repo.update_status(
                trace_id=trace_id,
                status=C10ExecutionStatus.SUCCEEDED
            )

            return ExecutionTrace.model_validate(updated_orm, from_attributes=True)

        except Exception as e:
            logger.error(f"AmplifiedRuntime failed for trace {trace_id}: {e}", exc_info=True)
            updated_orm = await self.trace_repo.update_status(
                trace_id=trace_id,
                status=C10ExecutionStatus.FAILED,
                error_message=str(e),
            )
            return ExecutionTrace.model_validate(updated_orm, from_attributes=True)