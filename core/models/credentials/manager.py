"""
Credential Manager Service (C2 §12-14).

Handles creation, rotation, revocation, and inspection of credentials.
Always returns opaque CredentialReference objects to callers (never raw secrets).
"""

from __future__ import annotations

from core.api.errors.exceptions import NotFoundError, ValidationError
from core.observability.logging import get_logger
from core.repositories.credential_repository import CredentialRepository
from core.repositories.provider_repository import ProviderRepository
from core.security.credentials import get_credential_encryptor
from schemas.domain import (
    CredentialReference,
    CredentialStatus,
    CredentialType,
)


logger = get_logger("dsrt.models.credentials.manager")


class CredentialManager:
    """Manages encrypted credential lifecycle."""

    def __init__(
        self,
        cred_repo: CredentialRepository,
        provider_repo: ProviderRepository,
    ) -> None:
        self._cred_repo = cred_repo
        self._provider_repo = provider_repo
        self._encryptor = get_credential_encryptor()

    async def create_credential(
        self,
        *,
        organization_id: str,
        provider_id: str,
        raw_secret: str,
        label: str = "",
        credential_type: CredentialType = CredentialType.BYOK,
    ) -> CredentialReference:
        """Encrypt and store a new API key/credential."""
        provider = await self._provider_repo.get_provider_by_id(provider_id)
        if not provider:
            raise NotFoundError(f"Provider '{provider_id}' not found.")

        if not raw_secret or not raw_secret.strip():
            raise ValidationError("Raw secret must not be empty.")

        encrypted = self._encryptor.encrypt(raw_secret)
        redacted = self._encryptor.redact(raw_secret)

        cred_orm = await self._cred_repo.create(
            organization_id=organization_id,
            provider_id=provider_id,
            credential_type=credential_type.value,
            label=label or f"{provider.name} ({credential_type.value.upper()})",
            encrypted_secret=encrypted,
            redacted_preview=redacted,
        )

        logger.info(
            "credential_created",
            credential_id=cred_orm.id,
            organization_id=organization_id,
            provider_id=provider_id,
            credential_type=credential_type.value,
        )

        return CredentialReference(
            id=cred_orm.id,
            organization_id=cred_orm.organization_id,
            provider_id=cred_orm.provider_id,
            credential_type=CredentialType(cred_orm.credential_type),
            status=CredentialStatus(cred_orm.status),
            label=cred_orm.label,
            created_at=cred_orm.created_at,
        )

    async def list_credentials(
        self,
        organization_id: str,
        provider_id: str | None = None,
        include_revoked: bool = False,
    ) -> list[CredentialReference]:
        """List opaque credential references for an organization."""
        creds = await self._cred_repo.list_by_organization(
            organization_id=organization_id,
            provider_id=provider_id,
            include_revoked=include_revoked,
        )
        return [
            CredentialReference(
                id=c.id,
                organization_id=c.organization_id,
                provider_id=c.provider_id,
                credential_type=CredentialType(c.credential_type),
                status=CredentialStatus(c.status),
                label=c.label,
                created_at=c.created_at,
                rotated_at=c.rotated_at,
                last_used_at=c.last_used_at,
                expires_at=c.expires_at,
            )
            for c in creds
        ]

    async def revoke_credential(self, organization_id: str, credential_id: str) -> None:
        """Revoke a credential."""
        cred = await self._cred_repo.get_by_id(credential_id)
        if not cred or cred.organization_id != organization_id:
            raise NotFoundError(f"Credential '{credential_id}' not found.")

        await self._cred_repo.revoke(cred)
        logger.info("credential_revoked", credential_id=credential_id, organization_id=organization_id)
