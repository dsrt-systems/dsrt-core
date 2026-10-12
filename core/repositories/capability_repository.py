"""Capability Repository — data access for system capabilities."""

from __future__ import annotations

from sqlalchemy import select

from core.repositories.base import Repository
from core.storage.models import Capability


class CapabilityRepository(Repository):
    async def get_by_id(self, capability_id: str) -> Capability | None:
        result = await self._session.execute(
            select(Capability).where(Capability.id == capability_id),
        )
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Capability | None:
        result = await self._session.execute(
            select(Capability).where(Capability.slug == slug),
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Capability]:
        result = await self._session.execute(
            select(Capability).order_by(Capability.slug),
        )
        return list(result.scalars().all())

    async def get_by_slugs(self, slugs: list[str]) -> list[Capability]:
        if not slugs:
            return []
        result = await self._session.execute(
            select(Capability).where(Capability.slug.in_(slugs)),
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        slug: str,
        name: str,
        description: str,
        version: str,
        input_schema: dict | None = None,
        output_schema: dict | None = None,
        requirements: dict | None = None,
        risk_level: str = "low",
    ) -> Capability:
        cap = Capability(
            slug=slug,
            name=name,
            description=description,
            version=version,
            input_schema=input_schema or {},
            output_schema=output_schema or {},
            requirements=requirements or {},
            risk_level=risk_level,
        )
        self._session.add(cap)
        await self._session.flush()
        return cap