"""Base abstract class for execution protocol handlers."""

from abc import ABC, abstractmethod
from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession

from core.execution.repositories.step_repository import ExecutionStepRepository
from core.execution.repositories.trace_repository import ExecutionTraceRepository
from schemas.domain.execution_c10 import ExecutionConfigurationCreate, ExecutionTrace


class BaseExecutionProtocol(ABC):
    """Abstract protocol contract for Direct, Amplified, and Paired execution flows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.trace_repo = ExecutionTraceRepository(session)
        self.step_repo = ExecutionStepRepository(session)

    @abstractmethod
    async def execute(
        self,
        trace_id: str,
        config: ExecutionConfigurationCreate,
        input_payload: Dict[str, Any],
    ) -> ExecutionTrace:
        """Executes the protocol, recording steps, claims, and metrics."""
        pass