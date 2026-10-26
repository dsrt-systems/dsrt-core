"""
/api/v1/executions endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.agents.registry import AgentRegistry
from core.api.dependencies import get_security_context
from core.kernel.kernel import ExecutionKernel
from core.repositories import (
    AgentRepository,
    CapabilityRepository,
    EventRepository,
    ExecutionRepository,
    TaskRepository,
)
from core.security.context import SecurityContext
from core.storage.database import get_db_session
from schemas.api.executions import ExecutionResponse, ExecutionTelemetryResponse
from schemas.domain import Artifact, Execution, ExecutionEvent, UsageRecord


router = APIRouter(prefix="/api/v1/executions", tags=["executions"])


def get_kernel(session: AsyncSession = Depends(get_db_session)) -> ExecutionKernel:
    task_repo = TaskRepository(session)
    exe_repo = ExecutionRepository(session)
    agent_repo = AgentRepository(session)
    cap_repo = CapabilityRepository(session)
    event_repo = EventRepository(session)
    agent_reg = AgentRegistry(agent_repo, cap_repo)
    return ExecutionKernel(
        task_repo=task_repo,
        execution_repo=exe_repo,
        agent_registry=agent_reg,
        event_repo=event_repo,
    )


def get_execution_repository(
    session: AsyncSession = Depends(get_db_session),
) -> ExecutionRepository:
    return ExecutionRepository(session)


@router.get("/{execution_id}", response_model=Execution, summary="Get execution state.")
async def get_execution(
    execution_id: str,
    exe_repo: ExecutionRepository = Depends(get_execution_repository),
    context: SecurityContext = Depends(get_security_context),
) -> Execution:
    exe_orm = await exe_repo.get_by_id(execution_id)
    if not exe_orm or not context.is_member_of(exe_orm.organization_id):
        from core.api.errors.exceptions import NotFoundError

        raise NotFoundError(f"Execution '{execution_id}' not found.")
    return Execution.model_validate(exe_orm, from_attributes=True)


@router.post(
    "/{execution_id}/cancel",
    response_model=ExecutionResponse,
    summary="Cancel an active execution.",
)
async def cancel_execution(
    execution_id: str,
    kernel: ExecutionKernel = Depends(get_kernel),
    context: SecurityContext = Depends(get_security_context),
) -> ExecutionResponse:
    exe = await kernel.cancel_execution(context, execution_id)
    return ExecutionResponse(execution=exe)


@router.get(
    "/{execution_id}/telemetry",
    response_model=ExecutionTelemetryResponse,
    summary="Export complete execution telemetry for Arena evaluation.",
)
async def get_execution_telemetry(
    execution_id: str,
    exe_repo: ExecutionRepository = Depends(get_execution_repository),
    context: SecurityContext = Depends(get_security_context),
) -> ExecutionTelemetryResponse:
    exe_orm = await exe_repo.get_by_id(execution_id)
    if not exe_orm or not context.is_member_of(exe_orm.organization_id):
        from core.api.errors.exceptions import NotFoundError

        raise NotFoundError(f"Execution '{execution_id}' not found.")

    exe_schema = Execution.model_validate(exe_orm, from_attributes=True)
    events = [ExecutionEvent.model_validate(e, from_attributes=True) for e in exe_orm.events]
    artifacts = [Artifact.model_validate(a, from_attributes=True) for a in exe_orm.artifacts]
    usage = [UsageRecord.model_validate(u, from_attributes=True) for u in exe_orm.usage_records]

    return ExecutionTelemetryResponse(
        execution=exe_schema,
        configuration_hash=exe_schema.configuration_hash,
        events=events,
        artifacts=artifacts,
        usage=usage,
    )