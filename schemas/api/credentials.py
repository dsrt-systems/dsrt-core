"""API schemas for /credentials endpoints."""

from __future__ import annotations

from pydantic import Field

from schemas.domain.base import DSRTSchema
from schemas.domain.enums import CredentialType
from schemas.domain.model_fabric import CredentialReference


class CredentialCreateRequest(DSRTSchema):
    provider_id: str
    raw_secret: str = Field(min_length=1, max_length=2000)
    label: str = ""
    credential_type: CredentialType = CredentialType.BYOK


class CredentialListResponse(DSRTSchema):
    credentials: list[CredentialReference]
    total: int