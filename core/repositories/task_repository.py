"""Task Repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.repositories.base import Repository
from core.storage.models import Task


class TaskRepository(Repository):
    async def get_by_id(self, task_id: str) -> Task | None:
        result = await self._session.execute(
            select(Task)
            .options(selectinload(Task.executions))
            .where(Task.id == task_id),
        )
        return result.scalar_one_or_none()

    async def list_by_organization(
        self, organization_id: str, limit: int = 50, offset: int = 0,
    ) -> list[Task]:
        result = await self._session.execute(
            select(Task)
            .options(selectinload(Task.executions))
            .where(Task.organization_id == organization_id)
            .order_by(Task.created_at.desc())
            .limit(limit)
            .offset(offset),
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        organization_id: str,
        user_id: str,
        agent_slug: str,
        objective: str,
        model_identifier: str | None = None,
        input_payload: dict | None = None,
        constraints: dict | None = None,
    ) -> Task:
        task = Task(
            organization_id=organization_id,
            user_id=user_id,
            agent_slug=agent_slug,
            model_identifier=model_identifier,
            objective=objective,
            input_payload=input_payload or {},
            constraints=constraints or {},
            status="CREATED",
        )
        self._session.add(task)
        await self._session.flush()
        return task

    async def update_status(self, task: Task, status: str) -> None:
        task.status = status
        await self._session.flush()