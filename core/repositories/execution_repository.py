"""Execution Repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.repositories.base import Repository
from core.storage.models import Execution
from core.storage.models.mixins import utcnow


class ExecutionRepository(Repository):
    async def get_by_id(self, execution_id: str) -> Execution | None:
        result = await self._session.execute(
            select(Execution)
            .options(
                selectinload(Execution.task),
                selectinload(Execution.events),
                selectinload(Execution.artifacts),
                selectinload(Execution.usage_records),  # <--- Added to prevent MissingGreenlet
            )
            .where(Execution.id == execution_id),
        )
        return result.scalar_one_or_none()

    async def list_by_task(self, task_id: str) -> list[Execution]:
        result = await self._session.execute(
            select(Execution)
            .where(Execution.task_id == task_id)
            .order_by(Execution.attempt.asc()),
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        task_id: str,
        organization_id: str,
        core_version: str,
        agent_version_id: str,
        contract_version: str,
        configuration_hash: str,
        model_id: str | None = None,
        attempt: int = 1,
        resource_limits: dict | None = None,
    ) -> Execution:
        execution = Execution(
            task_id=task_id,
            organization_id=organization_id,
            core_version=core_version,
            agent_version_id=agent_version_id,
            contract_version=contract_version,
            configuration_hash=configuration_hash,
            model_id=model_id,
            attempt=attempt,
            resource_limits=resource_limits or {},
            status="QUEUED",
            queued_at=utcnow(),
        )
        self._session.add(execution)
        await self._session.flush()
        return execution

    async def update_status(
        self,
        execution: Execution,
        status: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        error_metadata: dict | None = None,
        result_summary: dict | None = None,
    ) -> None:
        now = utcnow()
        execution.status = status

        if status == "RUNNING" and not execution.started_at:
            execution.started_at = now
        elif status in ("COMPLETED", "FAILED"):
            execution.completed_at = now
        elif status == "CANCELLED":
            execution.cancelled_at = now

        if error_code:
            execution.error_code = error_code
            execution.error_message = error_message
            execution.error_metadata = error_metadata
        if result_summary:
            execution.result_summary = result_summary

        await self._session.flush()