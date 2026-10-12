"""Unit tests for Credential Encryption Engine."""

import pytest

from core.security.credentials import CredentialEncryptor


def test_encryption_roundtrip():
    engine = CredentialEncryptor(secret_key="x" * 32)
    original = "sk-proj-1234567890abcdef"
    
    encrypted = engine.encrypt(original)
    assert encrypted != original
    assert len(encrypted) > 30

    decrypted = engine.decrypt(encrypted)
    assert decrypted == original


def test_redaction():
    assert CredentialEncryptor.redact("sk-1234567890abcdef") == "sk-...cdef"
    assert CredentialEncryptor.redact("short") == "***"


def test_encryption_rejects_empty():
    engine = CredentialEncryptor(secret_key="x" * 32)
    with pytest.raises(ValueError):
        engine.encrypt("")