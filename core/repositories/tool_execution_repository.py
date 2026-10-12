"""
Tool Execution Repository.

Handles persistence for ToolExecution, ToolObservation, and ToolUsageORM records.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.repositories.base import Repository
from core.storage.models.mixins import utcnow
from core.storage.models.tool_execution import ToolExecution, ToolObservation
from core.storage.models.tool_usage import ToolUsageORM


class ToolExecutionRepository(Repository):
    """Repository for tool execution lifecycle persistence."""

    async def create_execution(
        self,
        *,
        request_id: str,
        tool_slug: str,
        tool_version: str,
        execution_id: str,
        task_id: str,
        organization_id: str,
        agent_slug: str,
        agent_version: str,
        arguments: dict[str, Any],
        environment_instance_id: str | None = None,
        attempt: int = 1,
    ) -> ToolExecution:
        """Create a new ToolExecution record in REQUESTED status."""
        tool_exe = ToolExecution(
            request_id=request_id,
            tool_slug=tool_slug,
            tool_version=tool_version,
            execution_id=execution_id,
            task_id=task_id,
            organization_id=organization_id,
            agent_slug=agent_slug,
            agent_version=agent_version,
            arguments=arguments,
            environment_instance_id=environment_instance_id,
            status="REQUESTED",
            attempt=attempt,
        )
        self._session.add(tool_exe)
        await self._session.flush()
        return tool_exe

    async def get_by_id(self, tool_execution_id: str) -> ToolExecution | None:
        """Get a ToolExecution by primary key."""
        stmt = (
            select(ToolExecution)
            .where(ToolExecution.id == tool_execution_id)
            .options(
                selectinload(ToolExecution.observations),
                selectinload(ToolExecution.usage_records),
            )
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_request_id(self, request_id: str) -> ToolExecution | None:
        """Get a ToolExecution by its idempotency request_id."""
        stmt = select(ToolExecution).where(ToolExecution.request_id == request_id)
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def update_status(
        self,
        tool_exe: ToolExecution,
        status: str,
        *,
        output: dict[str, Any] | None = None,
        errors: list[dict[str, Any]] | None = None,
        duration_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ToolExecution:
        """Update the status and optional result fields of a ToolExecution."""
        now = utcnow()
        tool_exe.status = status

        if status == "STARTED" and not tool_exe.started_at:
            tool_exe.started_at = now
        elif status in ("COMPLETED", "FAILED", "CANCELLED"):
            tool_exe.completed_at = now
            if duration_ms is not None:
                tool_exe.duration_ms = duration_ms

        if output is not None:
            tool_exe.output = output
        if errors is not None:
            tool_exe.errors = errors
        if metadata is not None:
            tool_exe.metadata_json = metadata

        await self._session.flush()
        return tool_exe

    async def create_observation(
        self,
        *,
        tool_execution_id: str,
        execution_id: str,
        observation_type: str,
        content: Any = None,
        summary: str | None = None,
        source: str = "",
        confidence: float | None = None,
        truncated: bool = False,
        size_bytes: int = 0,
        artifact_id: str | None = None,
        provenance: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ToolObservation:
        """Create a ToolObservation linked to a ToolExecution."""
        obs = ToolObservation(
            tool_execution_id=tool_execution_id,
            execution_id=execution_id,
            observation_type=observation_type,
            content=content,
            summary=summary,
            source=source,
            confidence=confidence,
            truncated=truncated,
            size_bytes=size_bytes,
            artifact_id=artifact_id,
            provenance=provenance or {},
            metadata_json=metadata or {},
        )
        self._session.add(obs)
        await self._session.flush()
        return obs

    async def create_usage(
        self,
        *,
        tool_execution_id: str,
        execution_id: str,
        duration_ms: int = 0,
        cpu_ms: int | None = None,
        memory_mb_peak: float | None = None,
        network_bytes_in: int | None = None,
        network_bytes_out: int | None = None,
        storage_bytes: int | None = None,
        external_api_calls: int = 0,
        estimated_cost_usd: Decimal | None = None,
    ) -> ToolUsageORM:
        """Create a ToolUsageORM record for resource accounting."""
        usage = ToolUsageORM(
            tool_execution_id=tool_execution_id,
            execution_id=execution_id,
            duration_ms=duration_ms,
            cpu_ms=cpu_ms,
            memory_mb_peak=memory_mb_peak,
            network_bytes_in=network_bytes_in,
            network_bytes_out=network_bytes_out,
            storage_bytes=storage_bytes,
            external_api_calls=external_api_calls,
            estimated_cost_usd=estimated_cost_usd,
        )
        self._session.add(usage)
        await self._session.flush()
        return usage

    async def list_by_execution(
        self, execution_id: str, limit: int = 100,
    ) -> list[ToolExecution]:
        """List all tool executions for a given execution."""
        stmt = (
            select(ToolExecution)
            .where(ToolExecution.execution_id == execution_id)
            .order_by(ToolExecution.created_at.asc())
            .limit(limit)
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all())