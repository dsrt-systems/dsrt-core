"""Tests for configuration loading and URL normalization."""

import pytest
from pydantic import ValidationError

from core.config import DSRTSettings, _normalize_to_asyncpg, get_settings


class TestUrlNormalization:
    def test_postgresql_scheme_gets_asyncpg_driver(self):
        result = _normalize_to_asyncpg("postgresql://user:pass@host:5432/db")
        assert result == "postgresql+asyncpg://user:pass@host:5432/db"

    def test_postgres_scheme_gets_asyncpg_driver(self):
        result = _normalize_to_asyncpg("postgres://user:pass@host:5432/db")
        assert result == "postgresql+asyncpg://user:pass@host:5432/db"

    def test_asyncpg_scheme_is_unchanged(self):
        url = "postgresql+asyncpg://user:pass@host:5432/db"
        assert _normalize_to_asyncpg(url) == url

    def test_unknown_scheme_raises(self):
        with pytest.raises(ValueError, match="Cannot normalize"):
            _normalize_to_asyncpg("mysql://user:pass@host/db")


class TestSettingsValidation:
    """Test validation logic by constructing DSRTSettings directly.

    We avoid monkeypatch.setenv so we never mutate the shared get_settings() cache.
    """

    def _valid_kwargs(self) -> dict:
        return {
            "database_url": (
                "postgresql://postgres.abc:pw@aws-0-x.pooler.supabase.com:5432/postgres"
            ),
            "database_migration_url": (
                "postgresql://postgres:pw@db.abc.supabase.co:5432/postgres"
            ),
            "secret_key": "x" * 40,
        }

    def test_valid_urls_accepted(self):
        s = DSRTSettings(_env_file=None, **self._valid_kwargs())
        assert s.database_url.startswith("postgresql://")
        assert s.async_database_url.startswith("postgresql+asyncpg://")
        assert s.async_migration_url.startswith("postgresql+asyncpg://")

    def test_placeholder_url_rejected(self):
        kwargs = self._valid_kwargs()
        kwargs["database_url"] = (
            "postgresql://postgres.YOUR_PROJECT_REF:pw@host:5432/postgres"
        )
        with pytest.raises(ValidationError, match="placeholder"):
            DSRTSettings(_env_file=None, **kwargs)

    def test_unknown_scheme_rejected(self):
        kwargs = self._valid_kwargs()
        kwargs["database_url"] = "mongodb://host/db"
        with pytest.raises(ValidationError, match="postgresql://"):
            DSRTSettings(_env_file=None, **kwargs)

    def test_empty_url_rejected(self):
        kwargs = self._valid_kwargs()
        kwargs["database_url"] = ""
        with pytest.raises(ValidationError):
            DSRTSettings(_env_file=None, **kwargs)

    def test_short_secret_key_rejected(self):
        kwargs = self._valid_kwargs()
        kwargs["secret_key"] = "short"
        with pytest.raises(ValidationError):
            DSRTSettings(_env_file=None, **kwargs)

    def test_get_settings_returns_from_env(self):
        """Real settings load from actual .env — sanity check."""
        s = get_settings()
        assert s.database_url.startswith("postgresql://")
        assert s.database_schema == "dsrt"