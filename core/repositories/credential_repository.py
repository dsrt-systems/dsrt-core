"""Credential Repository."""
from __future__ import annotations

from sqlalchemy import delete, select

from core.repositories.base import Repository
from core.storage.models.credential import Credential


class CredentialRepository(Repository):
    """Repository for Credential ORM model."""

    async def create(
        self,
        organization_id: str,
        provider_id: str,
        credential_type: str,
        label: str,
        encrypted_secret: str,
        redacted_preview: str,
    ) -> Credential:
        cred = Credential(
            organization_id=organization_id,
            provider_id=provider_id,
            credential_type=credential_type,
            label=label,
            encrypted_secret=encrypted_secret,
            redacted_preview=redacted_preview,
        )
        self._session.add(cred)
        await self._session.flush()
        return cred

    async def get_by_id(self, credential_id: str) -> Credential | None:
        result = await self._session.execute(
            select(Credential).where(Credential.id == credential_id)
        )
        return result.scalar_one_or_none()

    async def list_by_organization(
        self,
        organization_id: str,
        provider_id: str | None = None,
        include_revoked: bool = False,
    ) -> list[Credential]:
        """List credentials for an organization, optionally filtered by provider and revocation status."""
        stmt = select(Credential).where(Credential.organization_id == organization_id)
        if not include_revoked:
            stmt = stmt.where(Credential.status != "revoked")
        if provider_id:
            stmt = stmt.where(Credential.provider_id == provider_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def revoke(self, cred: Credential) -> None:
        """Mark a credential as revoked."""
        cred.status = "revoked"
        await self._session.flush()

    async def delete(self, credential_id: str) -> bool:
        result = await self._session.execute(
            delete(Credential).where(Credential.id == credential_id)
        )
        await self._session.flush()
        return result.rowcount > 0
