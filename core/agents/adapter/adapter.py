"""
AgentAdapter — the Core socket into every Agent (C1 §16).

The Kernel drives the AgentAdapter; the AgentAdapter drives the DSRTAgent.
This layer isolates Core from any single agent implementation and enforces
the contract boundary.
"""

from __future__ import annotations

from core.api.errors.exceptions import AgentNotFoundError, DSRTError, ValidationError
from core.observability.logging import get_logger
from schemas.domain.enums import ErrorCode
from sdk.agent.contract import (
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentHealth,
    AgentInitializationRequest,
    AgentInitializationResult,
    DSRTAgent,
)
from sdk.agent.sdk import DSRTAgentSDK


logger = get_logger("dsrt.agents.adapter")


class AgentAdapter:
    """Core's mediator between the ExecutionKernel and a DSRTAgent instance."""

    def __init__(self, agent: DSRTAgent) -> None:
        self._agent = agent
        self._initialized = False
        self._cancelled = False

    @property
    def identity_id(self) -> str:
        return self._agent.identity.id

    @property
    def identity_version(self) -> str:
        return self._agent.identity.version

    async def initialize(
        self,
        sdk: DSRTAgentSDK,
        request: AgentInitializationRequest,
    ) -> AgentInitializationResult:
        """Initialize the agent with the injected SDK."""
        try:
            result = await self._agent.initialize(sdk, request)
        except Exception as e:
            logger.error(
                "agent_initialization_failed",
                agent_id=self.identity_id,
                error=str(e),
            )
            raise DSRTError(
                f"Agent '{self.identity_id}' failed to initialize.",
                metadata={"reason": str(e)},
                cause=e,
            ) from e

        if result.status != "READY":
            raise DSRTError(
                f"Agent '{self.identity_id}' returned non-READY init status.",
                metadata={"agent_status": result.status, "message": result.message},
            )

        self._initialized = True
        logger.info(
            "agent_initialized",
            agent_id=self.identity_id,
            version=self.identity_version,
        )
        return result

    async def execute(
        self, request: AgentExecutionRequest,
    ) -> AgentExecutionResult:
        """Execute the agent's professional workflow."""
        if not self._initialized:
            raise ValidationError(
                f"Agent '{self.identity_id}' must be initialized before execute()."
            )
        if self._cancelled:
            return AgentExecutionResult(
                status="CANCELLED",
                error_code=ErrorCode.EXECUTION_CANCELLED.value,
                error_message="Execution was cancelled before it could start.",
            )

        try:
            result = await self._agent.execute(request)
        except Exception as e:
            logger.error(
                "agent_execution_failed",
                agent_id=self.identity_id,
                execution_id=request.execution_id,
                error=str(e),
            )
            return AgentExecutionResult(
                status="FAILED",
                error_code=ErrorCode.AGENT_EXECUTION_FAILED.value,
                error_message=str(e),
            )

        logger.info(
            "agent_execution_completed",
            agent_id=self.identity_id,
            execution_id=request.execution_id,
            status=result.status,
        )
        return result

    async def cancel(self) -> None:
        """Signal cancellation to the agent."""
        self._cancelled = True
        try:
            await self._agent.cancel()
        except Exception as e:
            logger.warning(
                "agent_cancel_error_swallowed",
                agent_id=self.identity_id,
                error=str(e),
            )

    async def health(self) -> AgentHealth:
        """Ask the agent for its health status."""
        try:
            return await self._agent.health()
        except Exception as e:
            logger.warning(
                "agent_health_check_failed",
                agent_id=self.identity_id,
                error=str(e),
            )
            return AgentHealth(status="unhealthy", details={"error": str(e)})