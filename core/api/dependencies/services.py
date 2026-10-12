"""Service-layer dependencies."""

from __future__ import annotations

from fastapi import Depends

from core.api.dependencies.repositories import (
    get_organization_repository,
    get_user_repository,
)
from core.repositories import OrganizationRepository, UserRepository
from core.security.auth import AuthService


def get_auth_service(
    user_repo: UserRepository = Depends(get_user_repository),
    org_repo: OrganizationRepository = Depends(get_organization_repository),
) -> AuthService:
    return AuthService(user_repo=user_repo, organization_repo=org_repo)
