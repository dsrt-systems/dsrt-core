"""
Credential Broker (C2 §12).

The ONLY component authorized to decrypt secrets at execution time to pass to
ModelProviderAdapters. Decrypted keys live in-memory only for the duration of the request.
"""

from __future__ import annotations

from core.api.errors.exceptions import NotFoundError, ValidationError
from core.repositories.credential_repository import CredentialRepository
from core.security.credentials import get_credential_encryptor


class CredentialBroker:
    """Decrypts secrets in-memory for provider adapter calls."""

    def __init__(self, cred_repo: CredentialRepository) -> None:
        self._cred_repo = cred_repo
        self._encryptor = get_credential_encryptor()

    async def resolve_secret_key(
        self, organization_id: str, credential_id: str
    ) -> str:
        """Decrypt and return raw API key for provider invocation."""
        cred = await self._cred_repo.get_by_id(credential_id)
        if not cred or cred.organization_id != organization_id:
            raise NotFoundError(f"Credential '{credential_id}' not found.")

        if cred.status != "active":
            raise ValidationError(f"Credential '{credential_id}' is {cred.status}.")

        await self._cred_repo.mark_used(cred)
        return self._encryptor.decrypt(cred.encrypted_secret)