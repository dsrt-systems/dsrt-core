"""
DSRTAgentSDK Factory (C5.11 Update).

Assembles a fully-wired DSRTAgentSDK instance for a specific execution.
Now includes the Orchestration SDK for multi-agent coordination.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.agent import AgentManifest

from core.kernel.kernel import ExecutionKernel
from core.repositories import ExecutionRepository, TaskRepository
from core.version import AGENT_CONTRACT_VERSION, SDK_VERSION
from sdk.agent.adapters import (
    ArtifactSDKImpl,
    BenchmarkSDKImpl,
    ContextSDKImpl,
    EventSDKImpl,
    LoggingSDKImpl,
    MemorySDKImpl,
    ModelSDKImpl,
    StateSDKImpl,
    ToolSDKImpl,
    VerificationSDKImpl,
)
from sdk.agent.adapters.orchestration_adapter import OrchestrationSDKImpl
from sdk.agent.sdk import DSRTAgentSDK


def build_agent_sdk(
    *,
    session: AsyncSession,
    kernel: ExecutionKernel,
    execution_id: str,
    task_id: str,
    organization_id: str,
    user_id: str,
    agent_slug: str,
    agent_version: str,
    agent_version_id: str,
    agent_manifest: AgentManifest | None = None,
) -> DSRTAgentSDK:
    """Wire and return a DSRTAgentSDK for the given execution context."""
    task_repo = TaskRepository(session)
    execution_repo = ExecutionRepository(session)

    return DSRTAgentSDK(
        model=ModelSDKImpl(
            session=session,
            execution_id=execution_id,
            task_id=task_id,
            organization_id=organization_id,
            agent_slug=agent_slug,
        ),
        tools=ToolSDKImpl(
            session=session,
            kernel=kernel,
            execution_id=execution_id,
            task_id=task_id,
            organization_id=organization_id,
            agent_slug=agent_slug,
            agent_version=agent_version,
            agent_version_id=agent_version_id,
            agent_manifest=agent_manifest,
        ),
        context=ContextSDKImpl(
            task_repo=task_repo,
            execution_repo=execution_repo,
            execution_id=execution_id,
            agent_slug=agent_slug,
            agent_version=agent_version,
            user_id=user_id,
        ),
        memory=MemorySDKImpl(
            session=session,
            execution_id=execution_id,
            task_id=task_id,
            organization_id=organization_id,
            agent_slug=agent_slug,
        ),
        events=EventSDKImpl(
            kernel=kernel,
            execution_id=execution_id,
            agent_slug=agent_slug,
        ),
        artifacts=ArtifactSDKImpl(
            session=session,
            execution_id=execution_id,
            task_id=task_id,
            organization_id=organization_id,
            agent_slug=agent_slug,
            agent_version_id=agent_version_id,
        ),
        verification=VerificationSDKImpl(
            session=session,
            execution_id=execution_id,
        ),
        state=StateSDKImpl(),
        logging=LoggingSDKImpl(
            agent_slug=agent_slug,
            execution_id=execution_id,
            task_id=task_id,
            organization_id=organization_id,
        ),
        benchmark=BenchmarkSDKImpl(
            kernel=kernel,
            execution_id=execution_id,
            agent_slug=agent_slug,
        ),
        orchestration=OrchestrationSDKImpl(
            session=session,
            kernel=kernel,
            execution_id=execution_id,
            task_id=task_id,
            organization_id=organization_id,
            agent_slug=agent_slug,
        ),
        sdk_version=SDK_VERSION,
        contract_version=AGENT_CONTRACT_VERSION,
    )