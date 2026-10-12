"""
World Repository.

Handles persistence for World, WorldVersion, and WorldInstance records.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.repositories.base import Repository
from core.storage.models.world import WorldInstanceORM, WorldORM, WorldVersionORM


class WorldRepository(Repository):
    """Repository for world lifecycle persistence."""

    # --- World (blueprint) ---

    async def create_world(
        self,
        *,
        slug: str,
        name: str,
        publisher: str = "dsrt",
        description: str = "",
        metadata_json: dict[str, Any] | None = None,
    ) -> WorldORM:
        world = WorldORM(
            slug=slug,
            name=name,
            publisher=publisher,
            description=description,
            metadata_json=metadata_json or {},
        )
        self._session.add(world)
        await self._session.flush()
        return world

    async def get_by_slug(self, slug: str) -> WorldORM | None:
        stmt = (
            select(WorldORM)
            .where(WorldORM.slug == slug)
            .options(selectinload(WorldORM.versions))
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_worlds(self) -> list[WorldORM]:
        stmt = select(WorldORM).order_by(WorldORM.created_at.desc())
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def update_world(
        self, world: WorldORM, *, latest_version: str | None = None,
    ) -> WorldORM:
        if latest_version is not None:
            world.latest_version = latest_version
        await self._session.flush()
        return world

    # --- World Version ---

    async def create_version(
        self,
        *,
        world_id: str,
        version: str,
        manifest: dict[str, Any],
        implementation_class: str,
        metadata_json: dict[str, Any] | None = None,
    ) -> WorldVersionORM:
        ver = WorldVersionORM(
            world_id=world_id,
            version=version,
            manifest=manifest,
            implementation_class=implementation_class,
            metadata_json=metadata_json or {},
        )
        self._session.add(ver)
        await self._session.flush()
        return ver

    async def get_version(
        self, world_id: str, version: str,
    ) -> WorldVersionORM | None:
        stmt = (
            select(WorldVersionORM)
            .where(
                WorldVersionORM.world_id == world_id,
                WorldVersionORM.version == version,
            )
            .options(selectinload(WorldVersionORM.world))
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    # --- World Instance ---

    async def create_instance(
        self,
        *,
        world_version_id: str,
        organization_id: str,
        task_id: str | None = None,
        execution_id: str | None = None,
        status: str = "REGISTERED",
        policy: dict[str, Any],
        configuration_hash: str,
    ) -> WorldInstanceORM:
        inst = WorldInstanceORM(
            world_version_id=world_version_id,
            organization_id=organization_id,
            task_id=task_id,
            execution_id=execution_id,
            status=status,
            policy=policy,
            configuration_hash=configuration_hash,
        )
        self._session.add(inst)
        await self._session.flush()
        return inst

    async def get_instance_by_id(
        self, instance_id: str,
    ) -> WorldInstanceORM | None:
        stmt = (
            select(WorldInstanceORM)
            .where(WorldInstanceORM.id == instance_id)
            .options(selectinload(WorldInstanceORM.world_version))
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def update_instance(
        self,
        instance: WorldInstanceORM,
        *,
        status: str | None = None,
        started_at: datetime | None = None,
        stopped_at: datetime | None = None,
        destroyed_at: datetime | None = None,
    ) -> WorldInstanceORM:
        if status is not None:
            instance.status = status
        if started_at is not None:
            instance.started_at = started_at
        if stopped_at is not None:
            instance.stopped_at = stopped_at
        if destroyed_at is not None:
            instance.destroyed_at = destroyed_at
        await self._session.flush()
        return instance