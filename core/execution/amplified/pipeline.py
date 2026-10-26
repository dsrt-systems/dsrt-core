"""
C10.4 Amplification Runtime - Pipeline Orchestrator
Chains strategies securely, managing state transitions and DB step tracking.
"""

from typing import Dict, Any, List
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from schemas.domain.enums import StepKind, StepStatus, AmplificationStrategy
from core.execution.repositories.step_repository import ExecutionStepRepository
from core.execution.amplified.adapter import AmplifiedSubsystemAdapter
from core.execution.amplified.strategies.implementations import get_strategy_implementation

logger = logging.getLogger(__name__)


class AmplifiedPipeline:
    """Orchestrates the execution of a dynamic list of Amplification Strategies."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.step_repo = ExecutionStepRepository(session)
        self.adapter = AmplifiedSubsystemAdapter()

    async def execute_pipeline(
        self,
        trace_id: str,
        strategies: List[AmplificationStrategy],
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Runs the configured strategies sequentially, passing state forward."""
        if not strategies:
            # Default pipeline if none provided
            strategies = [
                AmplificationStrategy.CONTEXT_RETRIEVAL,
                AmplificationStrategy.PLANNING,
                AmplificationStrategy.TOOL_GROUNDED,
                AmplificationStrategy.VERIFICATION,
                AmplificationStrategy.REPAIR
            ]

        shared_state: Dict[str, Any] = {}
        total_tokens = 0
        total_duration_ms = 0.0
        steps_executed = 0

        for idx, strategy_enum in enumerate(strategies, start=1):
            strategy_impl = get_strategy_implementation(strategy_enum, self.adapter)
            
            # Create Step record for this stage
            step_orm = await self.step_repo.create_step(
                trace_id=trace_id,
                step_number=idx,
                kind=StepKind.AMPLIFICATION_STAGE,
                name=f"amplified_stage_{strategy_enum.value.lower()}",
                input_data={"payload": payload, "current_state_keys": list(shared_state.keys())}
            )

            try:
                # Execute strategy
                stage_metrics = await strategy_impl.execute(payload, shared_state)
                
                # Aggregate metrics
                tokens = stage_metrics.get("usage", {}).get("total_tokens", 0)
                duration = stage_metrics.get("duration_ms", 0.0)
                
                total_tokens += tokens
                total_duration_ms += duration
                steps_executed += 1

                # Complete step record
                await self.step_repo.update_step_status(
                    step_id=step_orm.id,
                    status=StepStatus.SUCCEEDED,
                    output_data=stage_metrics,
                    duration_ms=duration,
                    cost_usd=round(tokens * 0.000002, 6),
                    tokens_used=tokens
                )
                
            except Exception as e:
                logger.error(f"Amplification stage {strategy_enum.value} failed: {e}", exc_info=True)
                await self.step_repo.update_step_status(
                    step_id=step_orm.id,
                    status=StepStatus.FAILED,
                    error_message=str(e)
                )
                raise e

        # Final pipeline output aggregation
        return {
            "content": shared_state.get("model_output", ""),
            "pipeline_state": shared_state,
            "metrics": {
                "total_tokens": total_tokens,
                "duration_ms": total_duration_ms,
                "steps_executed": steps_executed
            }
        }