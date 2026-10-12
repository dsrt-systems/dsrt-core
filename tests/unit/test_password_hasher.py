"""Password hasher unit tests."""

import pytest

from core.security.passwords import PasswordHasher


class TestPasswordHasher:
    def test_hash_produces_bcrypt_format(self):
        h = PasswordHasher(rounds=4)
        result = h.hash("hello world")
        assert result.startswith("$2b$04$")

    def test_verify_accepts_correct_password(self):
        h = PasswordHasher(rounds=4)
        hashed = h.hash("correct-password")
        assert h.verify("correct-password", hashed) is True

    def test_verify_rejects_wrong_password(self):
        h = PasswordHasher(rounds=4)
        hashed = h.hash("correct-password")
        assert h.verify("wrong-password", hashed) is False

    def test_verify_rejects_empty_password(self):
        h = PasswordHasher(rounds=4)
        hashed = h.hash("abc")
        assert h.verify("", hashed) is False

    def test_verify_rejects_empty_hash(self):
        h = PasswordHasher(rounds=4)
        assert h.verify("abc", "") is False

    def test_verify_rejects_garbage_hash(self):
        h = PasswordHasher(rounds=4)
        assert h.verify("abc", "not-a-real-bcrypt-hash") is False

    def test_hash_rejects_empty(self):
        h = PasswordHasher(rounds=4)
        with pytest.raises(ValueError):
            h.hash("")

    def test_hash_rejects_too_long_password(self):
        h = PasswordHasher(rounds=4)
        with pytest.raises(ValueError):
            h.hash("x" * 73)

    def test_hash_rounds_validation(self):
        with pytest.raises(ValueError):
            PasswordHasher(rounds=3)
        with pytest.raises(ValueError):
            PasswordHasher(rounds=16)
