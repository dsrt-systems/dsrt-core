"""
/api/v1/tasks endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from core.agents.registry import AgentRegistry
from core.api.dependencies import (
    get_security_context,
    get_session,
    require_active_organization,
)
from core.kernel.kernel import ExecutionKernel
from core.repositories import (
    AgentRepository,
    CapabilityRepository,
    EventRepository,
    ExecutionRepository,
    TaskRepository,
)
from core.security.context import SecurityContext
from schemas.api.executions import ExecutionResponse
from schemas.api.tasks import TaskListResponse
from schemas.domain import Task, TaskCreate


router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


def get_kernel(session=Depends(get_session)) -> ExecutionKernel:
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


def get_task_repository(session=Depends(get_session)) -> TaskRepository:
    return TaskRepository(session)


@router.post(
    "",
    response_model=Task,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new Task.",
)
async def create_task(
    body: TaskCreate,
    kernel: ExecutionKernel = Depends(get_kernel),
    context: SecurityContext = Depends(require_active_organization),
) -> Task:
    return await kernel.create_task(context, body)


@router.get("", response_model=TaskListResponse, summary="List organization tasks.")
async def list_tasks(
    limit: int = 50,
    offset: int = 0,
    task_repo: TaskRepository = Depends(get_task_repository),
    context: SecurityContext = Depends(require_active_organization),
) -> TaskListResponse:
    tasks_orm = await task_repo.list_by_organization(
        context.active_organization_id, limit=limit, offset=offset,
    )
    tasks = [Task.model_validate(t, from_attributes=True) for t in tasks_orm]
    return TaskListResponse(tasks=tasks, total=len(tasks))


@router.get("/{task_id}", response_model=Task, summary="Get task details.")
async def get_task(
    task_id: str,
    task_repo: TaskRepository = Depends(get_task_repository),
    context: SecurityContext = Depends(get_security_context),
) -> Task:
    task_orm = await task_repo.get_by_id(task_id)
    if not task_orm or not context.is_member_of(task_orm.organization_id):
        from core.api.errors.exceptions import NotFoundError
        raise NotFoundError(f"Task '{task_id}' not found.")
    return Task.model_validate(task_orm, from_attributes=True)


@router.post(
    "/{task_id}/execute",
    response_model=ExecutionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create and queue a new Execution attempt for a Task.",
)
async def execute_task(
    task_id: str,
    kernel: ExecutionKernel = Depends(get_kernel),
    context: SecurityContext = Depends(get_security_context),
) -> ExecutionResponse:
    exe = await kernel.create_execution(context, task_id)
    return ExecutionResponse(execution=exe)