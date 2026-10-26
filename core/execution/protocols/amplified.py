"""
C10.4 Amplification Execution Protocol Implementation
Implements BaseExecutionProtocol for AMPLIFIED execution mode.
"""

from typing import Dict, Any
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from schemas.domain.execution_c10 import ExecutionConfigurationCreate, ExecutionTrace
from core.execution.protocols.base import BaseExecutionProtocol
from core.execution.amplified.runtime import AmplifiedRuntime

logger = logging.getLogger(__name__)


class AmplifiedExecutionProtocol(BaseExecutionProtocol):
    """
    Protocol driver implementation for AMPLIFIED mode executions.
    Delegates execution to the C10.4 AmplifiedRuntime.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.runtime = AmplifiedRuntime(session)

    async def execute(
        self,
        trace_id: str,
        config: ExecutionConfigurationCreate,
        input_payload: Dict[str, Any],
    ) -> ExecutionTrace:
        """
        Executes an AMPLIFIED mode trace using the full intelligence pipeline.
        """
        logger.info(f"AmplifiedExecutionProtocol executing trace {trace_id}")
        
        final_trace = await self.runtime.execute_trace(
            trace_id=trace_id,
            config=config,
            input_payload=input_payload,
        )
        return final_trace