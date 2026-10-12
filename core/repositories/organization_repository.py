"""Organization + membership repository."""

from __future__ import annotations

from sqlalchemy import select

from core.repositories.base import Repository
from core.storage.models import Organization, OrganizationMember


class OrganizationRepository(Repository):
    async def get_by_id(self, org_id: str) -> Organization | None:
        result = await self._session.execute(
            select(Organization).where(Organization.id == org_id),
        )
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Organization | None:
        result = await self._session.execute(
            select(Organization).where(Organization.slug == slug),
        )
        return result.scalar_one_or_none()

    async def slug_exists(self, slug: str) -> bool:
        return (await self.get_by_slug(slug)) is not None

    async def create(self, *, name: str, slug: str) -> Organization:
        org = Organization(name=name, slug=slug)
        self._session.add(org)
        await self._session.flush()
        return org

    async def add_member(
        self,
        *,
        organization_id: str,
        user_id: str,
        role: str,
    ) -> OrganizationMember:
        member = OrganizationMember(
            organization_id=organization_id,
            user_id=user_id,
            role=role,
        )
        self._session.add(member)
        await self._session.flush()
        return member

    async def get_membership(
        self, *, organization_id: str, user_id: str,
    ) -> OrganizationMember | None:
        result = await self._session.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == user_id,
            ),
        )
        return result.scalar_one_or_none()

    async def list_user_memberships(
        self, user_id: str,
    ) -> list[OrganizationMember]:
        result = await self._session.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == user_id,
            ),
        )
        return list(result.scalars().all())
