"""Organization, User, OrganizationMember schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import EmailStr, Field

from schemas.domain.base import DSRTSchema, TimestampedSchema
from schemas.domain.enums import OrganizationRole, OrganizationStatus, UserStatus


class OrganizationCreate(DSRTSchema):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")


class Organization(TimestampedSchema):
    id: str
    name: str
    slug: str
    status: OrganizationStatus


class UserCreate(DSRTSchema):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)


class User(TimestampedSchema):
    id: str
    email: EmailStr
    display_name: str
    status: UserStatus
    last_login_at: datetime | None = None


class OrganizationMember(TimestampedSchema):
    id: str
    organization_id: str
    user_id: str
    role: OrganizationRole