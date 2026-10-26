"""
Task Registry (C8 §8-12, §48-51).

Manages task suites, task definitions, and task instances.
Supports hidden evaluation state (C8 §9) and task randomization (C8 §11).
"""

from __future__ import annotations

import random
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.arena import (
    TaskDefinition,
    TaskInstance,
    TaskSuccessConditions,
)
from schemas.domain.enums import TaskVisibility

from core.api.errors.exceptions import ConflictError, NotFoundError
from core.observability.logging import get_logger
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.arena import (
    TaskDefinitionORM,
    TaskInstanceORM,
    TaskSuiteORM,
)


logger = get_logger("dsrt.arena.tasks")


class TaskRegistry:
    """Manages Arena task suites, definitions, and instances (C8 §8-12).

    Usage:
        registry = TaskRegistry(session)

        # Create a task suite
        suite = await registry.create_suite("research_suite", "Research Tasks v1")

        # Add a task definition with hidden evaluation state
        task = await registry.create_task(
            suite_id="research_suite",
            task_id="R001",
            objective="Investigate Company X",
            success_conditions={"minimum_sources": 5, "claims_verified": True},
            visibility="hidden",
        )

        # Generate a task instance (with optional randomization)
        instance = await registry.create_instance("R001", seed=42)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Task Suites
    # ------------------------------------------------------------------

    async def create_suite(
        self,
        suite_id: str,
        name: str,
        description: str = "",
        version: str = "1.0",
        organization_id: str | None = None,
    ) -> TaskSuiteORM:
        """Create a task suite (C8 §48)."""
        existing = await self._get_suite(suite_id)
        if existing:
            raise ConflictError(f"Task suite '{suite_id}' already exists.")

        suite = TaskSuiteORM(
            id=suite_id,
            name=name,
            description=description,
            version=version,
            organization_id=organization_id,
        )
        self._session.add(suite)
        await self._session.flush()

        logger.info("task_suite_created", suite_id=suite_id, name=name)
        return suite

    async def get_suite(self, suite_id: str) -> TaskSuiteORM:
        """Get a task suite by ID."""
        suite = await self._get_suite(suite_id)
        if not suite:
            raise NotFoundError(f"Task suite '{suite_id}' not found.")
        return suite

    async def list_suites(self, limit: int = 50) -> list[TaskSuiteORM]:
        """List all task suites."""
        stmt = select(TaskSuiteORM).order_by(TaskSuiteORM.id.asc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Task Definitions
    # ------------------------------------------------------------------

    async def create_task(
        self,
        *,
        task_id: str,
        objective: str,
        suite_id: str | None = None,
        version: str = "1.0",
        objective_type: str = "investigate",
        input_payload: dict[str, Any] | None = None,
        starting_world_snapshot: str | None = None,
        constraints: dict[str, Any] | None = None,
        success_conditions: dict[str, Any] | None = None,
        visibility: str = TaskVisibility.PUBLIC.value,
        metadata: dict[str, Any] | None = None,
    ) -> TaskDefinitionORM:
        """Create a task definition (C8 §8).

        The success_conditions dict is HIDDEN from agents (C8 §9).
        It is only visible to the evaluator.
        """
        existing = await self._get_task(task_id, version)
        if existing:
            raise ConflictError(
                f"Task '{task_id}' version '{version}' already exists."
            )

        task = TaskDefinitionORM(
            id=task_id,
            suite_id=suite_id,
            version=version,
            objective=objective,
            objective_type=objective_type,
            input_payload=input_payload or {},
            starting_world_snapshot=starting_world_snapshot,
            constraints=constraints or {},
            success_conditions=success_conditions or {},
            visibility=visibility,
            metadata_json=metadata or {},
        )
        self._session.add(task)
        await self._session.flush()

        logger.info(
            "task_definition_created",
            task_id=task_id,
            version=version,
            visibility=visibility,
            has_hidden_state=bool(success_conditions),
        )

        return task

    async def get_task(
        self, task_id: str, version: str | None = None,
    ) -> TaskDefinition:
        """Get a task definition as a domain schema."""
        orm = await self._get_task(task_id, version)
        if not orm:
            raise NotFoundError(f"Task '{task_id}' not found.")
        return self._to_domain(orm)

    async def get_task_orm(
        self, task_id: str, version: str | None = None,
    ) -> TaskDefinitionORM:
        """Get a task definition ORM record."""
        orm = await self._get_task(task_id, version)
        if not orm:
            raise NotFoundError(f"Task '{task_id}' not found.")
        return orm

    async def list_tasks(
        self,
        suite_id: str | None = None,
        visibility: str | None = None,
        limit: int = 100,
    ) -> list[TaskDefinition]:
        """List task definitions with optional filters."""
        stmt = select(TaskDefinitionORM).order_by(TaskDefinitionORM.id.asc())

        if suite_id:
            stmt = stmt.where(TaskDefinitionORM.suite_id == suite_id)
        if visibility:
            stmt = stmt.where(TaskDefinitionORM.visibility == visibility)

        stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return [self._to_domain(o) for o in result.scalars().all()]

    # ------------------------------------------------------------------
    # Task Instances (C8 §11-12)
    # ------------------------------------------------------------------

    async def create_instance(
        self,
        task_id: str,
        task_version: str | None = None,
        seed: int | None = None,
        configuration: dict[str, Any] | None = None,
    ) -> TaskInstanceORM:
        """Create a task instance, optionally randomized (C8 §11-12).

        If seed is provided, the instance is deterministic and reproducible.
        If no seed, a random one is generated.
        """
        task_orm = await self._get_task(task_id, task_version)
        if not task_orm:
            raise NotFoundError(f"Task '{task_id}' not found.")

        actual_seed = seed if seed is not None else random.randint(0, 2**31)

        # Build instance input from task definition + randomization
        instance_input = dict(task_orm.input_payload or {})
        if configuration:
            instance_input.update(configuration)

        # Hidden state is copied from the task definition
        # The agent never sees this — only the evaluator does
        hidden_state = dict(task_orm.success_conditions or {})

        instance = TaskInstanceORM(
            id=new_id(IdPrefix.TASK_INSTANCE),
            task_definition_id=task_orm.id,
            task_version=task_orm.version,
            seed=actual_seed,
            configuration=configuration or {},
            input_payload=instance_input,
            hidden_state=hidden_state,
        )
        self._session.add(instance)
        await self._session.flush()

        logger.info(
            "task_instance_created",
            instance_id=instance.id,
            task_id=task_id,
            seed=actual_seed,
        )

        return instance

    async def get_instance(
        self, instance_id: str,
    ) -> TaskInstanceORM | None:
        """Get a task instance by ID."""
        stmt = select(TaskInstanceORM).where(
            TaskInstanceORM.id == instance_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_suite(self, suite_id: str) -> TaskSuiteORM | None:
        stmt = select(TaskSuiteORM).where(TaskSuiteORM.id == suite_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_task(
        self, task_id: str, version: str | None = None,
    ) -> TaskDefinitionORM | None:
        stmt = select(TaskDefinitionORM).where(
            TaskDefinitionORM.id == task_id,
        )
        if version:
            stmt = stmt.where(TaskDefinitionORM.version == version)
        else:
            stmt = stmt.order_by(TaskDefinitionORM.version.desc()).limit(1)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def _to_domain(orm: TaskDefinitionORM) -> TaskDefinition:
        return TaskDefinition(
            id=orm.id,
            version=orm.version,
            suite_id=orm.suite_id or "",
            objective=orm.objective,
            objective_type=orm.objective_type,
            input_payload=orm.input_payload or {},
            starting_world_snapshot=orm.starting_world_snapshot,
            constraints=orm.constraints or {},
            success_conditions=TaskSuccessConditions(
                **(orm.success_conditions or {})
            ),
            visibility=TaskVisibility(orm.visibility),
            metadata=orm.metadata_json or {},
        )