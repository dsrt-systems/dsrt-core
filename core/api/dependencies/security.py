"""
Security dependencies — resolve the SecurityContext for every request.

Contract:
    - Extracts bearer token from Authorization header.
    - Decodes it via the TokenService.
    - Re-derives the user + memberships from the database.
    - Optionally binds the active organization from the X-DSRT-Organization header.
    - Never trusts client-supplied identity beyond the bearer token.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.api.dependencies.repositories import (
    get_organization_repository,
    get_user_repository,
)
from core.api.errors.exceptions import AuthenticationError, AuthorizationError
from core.repositories import OrganizationRepository, UserRepository
from core.security.context import OrganizationMembership, SecurityContext
from core.security.tokens import get_token_service
from schemas.domain.enums import OrganizationRole


bearer_scheme = HTTPBearer(auto_error=False)


async def get_security_context(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme),
    ] = None,
    user_repo: UserRepository = Depends(get_user_repository),
    org_repo: OrganizationRepository = Depends(get_organization_repository),
    x_dsrt_organization: Annotated[str | None, Header()] = None,
) -> SecurityContext:
    """Resolve the SecurityContext for the incoming request."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Missing or malformed Authorization header.")

    token_service = get_token_service()
    decoded = token_service.decode(credentials.credentials)

    user = await user_repo.get_by_id(decoded.user_id)
    if user is None or user.status != "active":
        raise AuthenticationError("Authenticated user is no longer active.")

    memberships_orm = await org_repo.list_user_memberships(user.id)
    memberships = tuple(
        OrganizationMembership(
            organization_id=m.organization_id,
            role=OrganizationRole(m.role),
        )
        for m in memberships_orm
    )

    # Resolve active organization.
    active_org_id: str | None = None
    if x_dsrt_organization:
        active_org_id = x_dsrt_organization.strip()
        if not any(m.organization_id == active_org_id for m in memberships):
            raise AuthorizationError(
                "You are not a member of the requested organization.",
                metadata={"organization_id": active_org_id},
            )
    elif len(memberships) == 1:
        # Single-membership convenience: default to the only org.
        active_org_id = memberships[0].organization_id

    return SecurityContext(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        memberships=memberships,
        active_organization_id=active_org_id,
        token_jti=decoded.jti,
    )


async def require_active_organization(
    context: SecurityContext = Depends(get_security_context),
) -> SecurityContext:
    """Require that the request has a resolved active organization."""
    if context.active_organization_id is None:
        raise AuthorizationError(
            "No active organization. Provide the X-DSRT-Organization header.",
        )
    return context
