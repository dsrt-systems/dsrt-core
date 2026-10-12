"""Token service unit tests."""

from datetime import timedelta

import pytest

from core.api.errors.exceptions import AuthenticationError
from core.security.tokens import TokenService


SECRET = "x" * 40


class TestTokenService:
    def test_issue_and_decode_roundtrip(self):
        svc = TokenService(secret_key=SECRET, algorithm="HS256", expire_minutes=15)
        token, meta = svc.issue_access_token(user_id="usr_123")
        assert isinstance(token, str) and len(token) > 20
        assert meta.user_id == "usr_123"

        decoded = svc.decode(token)
        assert decoded.user_id == "usr_123"
        assert decoded.jti == meta.jti

    def test_expired_token_rejected(self):
        svc = TokenService(secret_key=SECRET, algorithm="HS256", expire_minutes=-1)
        token, _ = svc.issue_access_token(user_id="usr_123")
        with pytest.raises(AuthenticationError):
            svc.decode(token)

    def test_tampered_token_rejected(self):
        svc = TokenService(secret_key=SECRET, algorithm="HS256", expire_minutes=15)
        token, _ = svc.issue_access_token(user_id="usr_123")
        tampered = token[:-2] + ("AA" if token[-2:] != "AA" else "BB")
        with pytest.raises(AuthenticationError):
            svc.decode(tampered)

    def test_wrong_secret_rejected(self):
        svc1 = TokenService(secret_key=SECRET, algorithm="HS256", expire_minutes=15)
        svc2 = TokenService(secret_key="y" * 40, algorithm="HS256", expire_minutes=15)
        token, _ = svc1.issue_access_token(user_id="usr_123")
        with pytest.raises(AuthenticationError):
            svc2.decode(token)

    def test_empty_token_rejected(self):
        svc = TokenService(secret_key=SECRET, algorithm="HS256", expire_minutes=15)
        with pytest.raises(AuthenticationError):
            svc.decode("")

    def test_short_secret_rejected(self):
        with pytest.raises(ValueError):
            TokenService(secret_key="short", algorithm="HS256", expire_minutes=15)
