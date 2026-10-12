"""
/api/v1/executions/{execution_id}/events endpoint (Trajectory view).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from core.api.dependencies import get_security_context, get_session
from core.api.errors.exceptions import NotFoundError
from core.repositories import EventRepository, ExecutionRepository
from core.security.context import SecurityContext
from schemas.api.events import EventListResponse
from schemas.domain import ExecutionEvent


router = APIRouter(prefix="/api/v1/executions", tags=["events"])


def get_event_repository(session=Depends(get_session)) -> EventRepository:
    return EventRepository(session)


def get_execution_repository(session=Depends(get_session)) -> ExecutionRepository:
    return ExecutionRepository(session)


@router.get(
    "/{execution_id}/events",
    response_model=EventListResponse,
    summary="Get execution trajectory events in sequence order.",
)
async def list_execution_events(
    execution_id: str,
    since_sequence: int = 0,
    limit: int = 100,
    event_repo: EventRepository = Depends(get_event_repository),
    exe_repo: ExecutionRepository = Depends(get_execution_repository),
    context: SecurityContext = Depends(get_security_context),
) -> EventListResponse:
    exe_orm = await exe_repo.get_by_id(execution_id)
    if not exe_orm or not context.is_member_of(exe_orm.organization_id):
        raise NotFoundError(f"Execution '{execution_id}' not found.")

    events_orm = await event_repo.list_by_execution(
        execution_id, since_sequence=since_sequence, limit=limit,
    )
    events = [ExecutionEvent.model_validate(e, from_attributes=True) for e in events_orm]

    return EventListResponse(
        events=events,
        total=len(events),
        execution_id=execution_id,
    )