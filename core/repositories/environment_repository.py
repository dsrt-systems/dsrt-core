"""
Environment Repository.

Handles persistence for Environment, EnvironmentVersion,
EnvironmentInstance, and EnvironmentSnapshot records.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.repositories.base import Repository
from core.storage.models.environment import (
    EnvironmentInstanceORM,
    EnvironmentORM,
    EnvironmentSnapshotORM,
    EnvironmentVersionORM,
)


class EnvironmentRepository(Repository):
    """Repository for environment lifecycle persistence."""

    # --- Environment (blueprint) ---

    async def create_environment(
        self,
        *,
        slug: str,
        name: str,
        environment_type: str,
        publisher: str = "dsrt",
        description: str = "",
        metadata_json: dict[str, Any] | None = None,
    ) -> EnvironmentORM:
        env = EnvironmentORM(
            slug=slug,
            name=name,
            environment_type=environment_type,
            publisher=publisher,
            description=description,
            metadata_json=metadata_json or {},
        )
        self._session.add(env)
        await self._session.flush()
        return env

    async def get_by_slug(self, slug: str) -> EnvironmentORM | None:
        stmt = (
            select(EnvironmentORM)
            .where(EnvironmentORM.slug == slug)
            .options(selectinload(EnvironmentORM.versions))
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_id(self, env_id: str) -> EnvironmentORM | None:
        stmt = (
            select(EnvironmentORM)
            .where(EnvironmentORM.id == env_id)
            .options(selectinload(EnvironmentORM.versions))
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_environments(self) -> list[EnvironmentORM]:
        stmt = select(EnvironmentORM).order_by(EnvironmentORM.created_at.desc())
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def update_environment(
        self,
        env: EnvironmentORM,
        *,
        latest_version: str | None = None,
    ) -> EnvironmentORM:
        if latest_version is not None:
            env.latest_version = latest_version
        await self._session.flush()
        return env

    # --- Environment Version ---

    async def create_version(
        self,
        *,
        environment_id: str,
        version: str,
        manifest: dict[str, Any],
        implementation_class: str,
        metadata_json: dict[str, Any] | None = None,
    ) -> EnvironmentVersionORM:
        ver = EnvironmentVersionORM(
            environment_id=environment_id,
            version=version,
            manifest=manifest,
            implementation_class=implementation_class,
            metadata_json=metadata_json or {},
        )
        self._session.add(ver)
        await self._session.flush()
        return ver

    async def get_version(
        self, environment_id: str, version: str,
    ) -> EnvironmentVersionORM | None:
        stmt = (
            select(EnvironmentVersionORM)
            .where(
                EnvironmentVersionORM.environment_id == environment_id,
                EnvironmentVersionORM.version == version,
            )
            .options(selectinload(EnvironmentVersionORM.environment))
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    # --- Environment Instance ---

    async def create_instance(
        self,
        *,
        environment_version_id: str,
        environment_type: str,
        organization_id: str,
        task_id: str | None = None,
        execution_id: str | None = None,
        world_instance_id: str | None = None,
        status: str = "REQUESTED",
        resource_profile: dict[str, Any] | None = None,
        network_policy: dict[str, Any] | None = None,
        filesystem_policy: dict[str, Any] | None = None,
    ) -> EnvironmentInstanceORM:
        inst = EnvironmentInstanceORM(
            environment_version_id=environment_version_id,
            environment_type=environment_type,
            organization_id=organization_id,
            task_id=task_id,
            execution_id=execution_id,
            world_instance_id=world_instance_id,
            status=status,
            resource_profile=resource_profile or {},
            network_policy=network_policy or {},
            filesystem_policy=filesystem_policy or {},
        )
        self._session.add(inst)
        await self._session.flush()
        return inst

    async def get_instance_by_id(
        self, instance_id: str,
    ) -> EnvironmentInstanceORM | None:
        stmt = (
            select(EnvironmentInstanceORM)
            .where(EnvironmentInstanceORM.id == instance_id)
            .options(
                selectinload(EnvironmentInstanceORM.environment_version),
                selectinload(EnvironmentInstanceORM.snapshots),
            )
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_instance_by_execution(
        self, execution_id: str,
    ) -> EnvironmentInstanceORM | None:
        stmt = (
            select(EnvironmentInstanceORM)
            .where(EnvironmentInstanceORM.execution_id == execution_id)
            .order_by(EnvironmentInstanceORM.created_at.desc())
        )
        res = await self._session.execute(stmt)
        return res.scalars().first()

    async def update_instance(
        self,
        instance: EnvironmentInstanceORM,
        *,
        status: str | None = None,
        workspace_root: str | None = None,
        runtime_reference: str | None = None,
        started_at: datetime | None = None,
        stopped_at: datetime | None = None,
        destroyed_at: datetime | None = None,
    ) -> EnvironmentInstanceORM:
        if status is not None:
            instance.status = status
        if workspace_root is not None:
            instance.workspace_root = workspace_root
        if runtime_reference is not None:
            instance.runtime_reference = runtime_reference
        if started_at is not None:
            instance.started_at = started_at
        if stopped_at is not None:
            instance.stopped_at = stopped_at
        if destroyed_at is not None:
            instance.destroyed_at = destroyed_at
        await self._session.flush()
        return instance

    # --- Environment Snapshot ---

    async def create_snapshot(
        self,
        *,
        environment_instance_id: str,
        snapshot_type: str = "checkpoint",
        state_hash: str,
        configuration_hash: str,
        size_bytes: int = 0,
        storage_reference: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EnvironmentSnapshotORM:
        snap = EnvironmentSnapshotORM(
            environment_instance_id=environment_instance_id,
            snapshot_type=snapshot_type,
            state_hash=state_hash,
            configuration_hash=configuration_hash,
            size_bytes=size_bytes,
            storage_reference=storage_reference,
            metadata_json=metadata or {},
        )
        self._session.add(snap)
        await self._session.flush()
        return snap