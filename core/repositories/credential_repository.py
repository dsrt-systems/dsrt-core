"""
Credential Repository.

Data access for encrypted credentials.
"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.repositories.base import Repository
from core.storage.models import Credential
from core.storage.models.mixins import utcnow


class CredentialRepository(Repository):
    async def get_by_id(self, credential_id: str) -> Credential | None:
        result = await self._session.execute(
            select(Credential)
            .options(selectinload(Credential.provider))
            .where(Credential.id == credential_id)
        )
        return result.scalar_one_or_none()

    async def list_by_organization(
        self, organization_id: str, provider_id: str | None = None
    ) -> list[Credential]:
        stmt = (
            select(Credential)
            .options(selectinload(Credential.provider))
            .where(
                Credential.organization_id == organization_id,
                Credential.status == "active",
            )
        )
        if provider_id:
            stmt = stmt.where(Credential.provider_id == provider_id)

        result = await self._session.execute(stmt.order_by(Credential.created_at.desc()))
        return list(result.scalars().all())

    async def create(
        self,
        *,
        organization_id: str,
        provider_id: str,
        credential_type: str,
        label: str,
        encrypted_secret: str,
        redacted_preview: str,
        expires_at: datetime | None = None,
    ) -> Credential:
        cred = Credential(
            organization_id=organization_id,
            provider_id=provider_id,
            credential_type=credential_type,
            label=label,
            encrypted_secret=encrypted_secret,
            redacted_preview=redacted_preview,
            status="active",
            expires_at=expires_at,
        )
        self._session.add(cred)
        await self._session.flush()
        return cred

    async def mark_used(self, credential: Credential) -> None:
        credential.last_used_at = utcnow()
        await self._session.flush()

    async def revoke(self, credential: Credential) -> None:
        credential.status = "revoked"
        await self._session.flush()