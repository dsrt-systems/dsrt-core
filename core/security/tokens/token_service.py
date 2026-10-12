"""
JWT Token Service.

Issues and validates short-lived access tokens. Tokens carry the MINIMUM
required claims (user_id + jti). Full identity is re-derived from the database
on every request — no user profile data is embedded in the token.

Tokens are opaque to the agent SDK.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt

from core.api.errors.exceptions import AuthenticationError
from core.config import get_settings
from core.storage.identifiers import IdPrefix, new_id


DSRT_TOKEN_ISSUER = "dsrt-core"
DSRT_TOKEN_AUDIENCE = "dsrt-api"


@dataclass(frozen=True)
class DecodedToken:
    """Parsed access-token claims."""

    user_id: str
    jti: str
    issued_at: datetime
    expires_at: datetime


class TokenService:
    """Issues and verifies DSRT access tokens."""

    def __init__(
        self,
        *,
        secret_key: str,
        algorithm: str,
        expire_minutes: int,
    ) -> None:
        if len(secret_key) < 32:
            raise ValueError("Token secret key must be at least 32 characters.")
        self._secret_key = secret_key
        self._algorithm = algorithm
        self._expire_minutes = expire_minutes

    def issue_access_token(self, *, user_id: str) -> tuple[str, DecodedToken]:
        """Issue a new access token for a user."""
        now = datetime.now(timezone.utc)
        expires = now + timedelta(minutes=self._expire_minutes)
        jti = new_id(IdPrefix.REQUEST)
        payload: dict[str, Any] = {
            "iss": DSRT_TOKEN_ISSUER,
            "aud": DSRT_TOKEN_AUDIENCE,
            "sub": user_id,
            "jti": jti,
            "iat": int(now.timestamp()),
            "exp": int(expires.timestamp()),
        }
        token = jwt.encode(payload, self._secret_key, algorithm=self._algorithm)
        return token, DecodedToken(
            user_id=user_id,
            jti=jti,
            issued_at=now,
            expires_at=expires,
        )

    def decode(self, token: str) -> DecodedToken:
        """Decode and validate a token; raise AuthenticationError on failure."""
        if not token:
            raise AuthenticationError("Missing access token.")
        try:
            payload = jwt.decode(
                token,
                self._secret_key,
                algorithms=[self._algorithm],
                issuer=DSRT_TOKEN_ISSUER,
                audience=DSRT_TOKEN_AUDIENCE,
            )
        except JWTError as e:
            raise AuthenticationError(
                "Invalid or expired access token.",
                metadata={"reason": type(e).__name__},
                cause=e,
            ) from e

        user_id = payload.get("sub")
        jti = payload.get("jti")
        iat = payload.get("iat")
        exp = payload.get("exp")
        if not (user_id and jti and iat and exp):
            raise AuthenticationError("Token payload is missing required claims.")

        return DecodedToken(
            user_id=user_id,
            jti=jti,
            issued_at=datetime.fromtimestamp(iat, tz=timezone.utc),
            expires_at=datetime.fromtimestamp(exp, tz=timezone.utc),
        )


_token_service: TokenService | None = None


def get_token_service() -> TokenService:
    """Return the process-wide token service."""
    global _token_service
    if _token_service is None:
        settings = get_settings()
        _token_service = TokenService(
            secret_key=settings.secret_key,
            algorithm=settings.algorithm,
            expire_minutes=settings.access_token_expire_minutes,
        )
    return _token_service
