"""
/auth endpoints.

    POST /api/v1/auth/register
    POST /api/v1/auth/login
    GET  /api/v1/auth/me
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from core.api.dependencies import get_auth_service, get_security_context
from core.security.auth import AuthService
from core.security.context import SecurityContext
from schemas.api.auth import (
    LoginRequest,
    LoginResponse,
    MembershipSummary,
    MeResponse,
    OrganizationSummary,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserSummary,
)


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user and initial organization.",
)
async def register(
    body: RegisterRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> RegisterResponse:
    result = await auth_service.register_user_with_organization(
        email=body.email,
        display_name=body.display_name,
        password=body.password,
        organization_name=body.organization_name,
        organization_slug=body.organization_slug,
    )
    return RegisterResponse(
        user=UserSummary(
            id=result.user.id,
            email=result.user.email,
            display_name=result.user.display_name,
        ),
        organization=OrganizationSummary(
            id=result.organization.id,
            name=result.organization.name,
            slug=result.organization.slug,
        ),
        token=TokenResponse(access_token=result.access_token),
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Exchange credentials for an access token.",
)
async def login(
    body: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> LoginResponse:
    result = await auth_service.authenticate(
        email=body.email, password=body.password,
    )
    return LoginResponse(
        user=UserSummary(
            id=result.user.id,
            email=result.user.email,
            display_name=result.user.display_name,
        ),
        token=TokenResponse(access_token=result.access_token),
    )


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Return the authenticated identity and memberships.",
)
async def me(
    context: SecurityContext = Depends(get_security_context),
) -> MeResponse:
    return MeResponse(
        user=UserSummary(
            id=context.user_id,
            email=context.email,
            display_name=context.display_name,
        ),
        memberships=[
            MembershipSummary(
                organization_id=m.organization_id,
                role=m.role,
            )
            for m in context.memberships
        ],
        active_organization_id=context.active_organization_id,
    )
