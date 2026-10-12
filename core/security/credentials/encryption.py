"""
Credential Encryption Engine (C2 §12).

Uses AES-256 Fernet symmetric encryption derived from DSRT_SECRET_KEY.
Ensures zero plaintext API keys touch database storage or logs.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet

from core.config import get_settings


class CredentialEncryptor:
    """Fernet-based AES-256 encryption engine."""

    def __init__(self, secret_key: str | None = None) -> None:
        raw_secret = secret_key or get_settings().secret_key
        if len(raw_secret) < 32:
            raise ValueError("Secret key must be at least 32 characters.")

        # Derive a valid 32-byte urlsafe base64 Fernet key from DSRT_SECRET_KEY
        key_bytes = hashlib.sha256(raw_secret.encode("utf-8")).digest()
        fernet_key = base64.urlsafe_b64encode(key_bytes)
        self._fernet = Fernet(fernet_key)

    def encrypt(self, plaintext_secret: str) -> str:
        """Encrypt a raw API key/secret into ciphertext string."""
        if not plaintext_secret or not plaintext_secret.strip():
            raise ValueError("Cannot encrypt an empty secret.")
        
        token_bytes = self._fernet.encrypt(plaintext_secret.strip().encode("utf-8"))
        return token_bytes.decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a stored ciphertext token back to plaintext secret."""
        if not ciphertext or not ciphertext.strip():
            raise ValueError("Cannot decrypt an empty ciphertext.")
            
        try:
            plaintext_bytes = self._fernet.decrypt(ciphertext.encode("utf-8"))
            return plaintext_bytes.decode("utf-8")
        except Exception as e:
            raise ValueError("Failed to decrypt secret: invalid key or corrupted data.") from e

    @staticmethod
    def redact(secret: str) -> str:
        """Return a safe redacted version of a secret for display/audit (e.g. 'sk-...4a2b')."""
        clean = secret.strip()
        if len(clean) <= 8:
            return "***"
        prefix = clean[:3]
        suffix = clean[-4:]
        return f"{prefix}...{suffix}"


_encryptor: CredentialEncryptor | None = None


def get_credential_encryptor() -> CredentialEncryptor:
    global _encryptor
    if _encryptor is None:
        _encryptor = CredentialEncryptor()
    return _encryptor