"""API request/response schemas for /auth endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import EmailStr, Field

from schemas.domain.base import DSRTSchema
from schemas.domain.enums import OrganizationRole


# --- Registration ---

class RegisterRequest(DSRTSchema):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=72)
    organization_name: str = Field(min_length=1, max_length=200)
    organization_slug: str = Field(
        min_length=2, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$",
    )


class OrganizationSummary(DSRTSchema):
    id: str
    name: str
    slug: str


class UserSummary(DSRTSchema):
    id: str
    email: EmailStr
    display_name: str


class TokenResponse(DSRTSchema):
    access_token: str
    token_type: str = "bearer"


class RegisterResponse(DSRTSchema):
    user: UserSummary
    organization: OrganizationSummary
    token: TokenResponse


# --- Login ---

class LoginRequest(DSRTSchema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class LoginResponse(DSRTSchema):
    user: UserSummary
    token: TokenResponse


# --- Current user ---

class MembershipSummary(DSRTSchema):
    organization_id: str
    role: OrganizationRole


class MeResponse(DSRTSchema):
    user: UserSummary
    memberships: list[MembershipSummary]
    active_organization_id: str | None
