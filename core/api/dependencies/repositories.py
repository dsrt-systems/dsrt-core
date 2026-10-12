"""Repository dependencies."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.api.dependencies.database import get_session
from core.repositories import OrganizationRepository, UserRepository


def get_user_repository(
    session: AsyncSession = Depends(get_session),
) -> UserRepository:
    return UserRepository(session)


def get_organization_repository(
    session: AsyncSession = Depends(get_session),
) -> OrganizationRepository:
    return OrganizationRepository(session)
