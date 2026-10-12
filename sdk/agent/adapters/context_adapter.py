"""
ContextSDK Implementation.

Assembles the SDKAgentContext from Task + Execution + AgentVersion state.
"""

from __future__ import annotations

from typing import Any

from core.repositories import ExecutionRepository, TaskRepository
from sdk.agent.interfaces.context import SDKAgentContext


class ContextSDKImpl:
    """Concrete implementation of ContextSDK."""

    def __init__(
        self,
        task_repo: TaskRepository,
        execution_repo: ExecutionRepository,
        execution_id: str,
        agent_slug: str,
        agent_version: str,
        user_id: str,
    ) -> None:
        self._tasks = task_repo
        self._executions = execution_repo
        self._execution_id = execution_id
        self._agent_slug = agent_slug
        self._agent_version = agent_version
        self._user_id = user_id
        self._working_state: dict[str, Any] = {}

    async def get(self) -> SDKAgentContext:
        exe = await self._executions.get_by_id(self._execution_id)
        if exe is None:
            raise RuntimeError(
                f"Context unavailable: execution {self._execution_id} not found."
            )
        task = await self._tasks.get_by_id(exe.task_id)
        if task is None:
            raise RuntimeError(
                f"Context unavailable: task {exe.task_id} not found."
            )

        return SDKAgentContext(
            execution_id=exe.id,
            task_id=task.id,
            organization_id=exe.organization_id,
            user_id=self._user_id,
            agent_slug=self._agent_slug,
            agent_version=self._agent_version,
            objective=task.objective,
            input_payload=dict(task.input_payload or {}),
            working_state=dict(self._working_state),
            constraints=dict(task.constraints or {}),
            resource_limits=dict(exe.resource_limits or {}),
            configuration_hash=exe.configuration_hash,
        )

    async def update_state(self, patch: dict[str, Any]) -> None:
        """In-memory patch (durable persistence arrives in C4)."""
        self._working_state.update(patch)