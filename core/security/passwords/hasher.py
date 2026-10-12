"""
Password hashing service.

Uses bcrypt with a configurable cost factor. The hasher is a class so that
it can be replaced or wrapped for testing without touching call sites.

Passwords must NEVER appear in logs, events, tokens, artifacts, or exceptions.
"""

from __future__ import annotations

import bcrypt


class PasswordHasher:
    """bcrypt-based password hasher."""

    # bcrypt's default is 12; production may raise this.
    def __init__(self, rounds: int = 12) -> None:
        if rounds < 4 or rounds > 15:
            raise ValueError("bcrypt rounds must be between 4 and 15.")
        self._rounds = rounds

    def hash(self, plaintext: str) -> str:
        """Return a bcrypt hash of the given password."""
        if not plaintext:
            raise ValueError("Password must be non-empty.")
        # bcrypt has a 72-byte input limit; enforce explicitly.
        pw_bytes = plaintext.encode("utf-8")
        if len(pw_bytes) > 72:
            raise ValueError("Password must be 72 bytes or fewer.")
        salt = bcrypt.gensalt(rounds=self._rounds)
        return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")

    def verify(self, plaintext: str, hashed: str) -> bool:
        """Verify a plaintext password against a stored hash."""
        if not plaintext or not hashed:
            return False
        try:
            return bcrypt.checkpw(
                plaintext.encode("utf-8"), hashed.encode("utf-8"),
            )
        except (ValueError, TypeError):
            return False


# Default singleton hasher.
_default_hasher = PasswordHasher()


def get_password_hasher() -> PasswordHasher:
    """Return the default DSRT password hasher."""
    return _default_hasher
