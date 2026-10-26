"""DSRT Core Configuration."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

def _normalize_to_asyncpg(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"): return url
    if url.startswith("postgresql://"): return "postgresql+asyncpg://" + url[13:]
    if url.startswith("postgres://"): return "postgresql+asyncpg://" + url[11:]
    raise ValueError("Cannot normalize database URL.")

class DSRTSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="DSRT_", case_sensitive=False, extra="ignore")

    core_version: str = "1.0.0"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    testing: bool = False

    log_level: str = "INFO"
    log_format: str = "json"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 1
    api_reload: bool = False
    cors_origins: str = "*"

    database_schema: str = "dsrt"
    database_url: str
    database_migration_url: str
    database_pool_min: int = 5
    database_pool_max: int = 20

    @field_validator("database_url", "database_migration_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("database URL must not be empty")
        
        v_lower = v.lower()
        if any(marker in v_lower for marker in ["placeholder", "your_project", "your-project", "change_me", "replace_me"]):
            raise ValueError("placeholder database URL detected")
            
        if not (v.startswith("postgresql://") or v.startswith("postgres://") or v.startswith("postgresql+asyncpg://")):
            raise ValueError("database URL scheme must be postgresql://")
            
        return v

    @property
    def async_database_url(self) -> str:
        return _normalize_to_asyncpg(self.database_url)

    @property
    def async_migration_url(self) -> str:
        return _normalize_to_asyncpg(self.database_migration_url)

    secret_key: str = "a"*32
    access_token_expire_minutes: int = 60
    algorithm: str = "HS256"
    credential_encryption_key: str = "a"*32

    @field_validator("secret_key", "credential_encryption_key")
    @classmethod
    def validate_keys(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("secret key must be at least 32 characters long")
        return v

    default_execution_timeout_seconds: int = 1800
    default_max_model_calls: int = 100
    default_max_tool_calls: int = 500
    default_max_storage_mb: int = 500

    python_sandbox_max_runtime_seconds: int = 30
    python_sandbox_max_memory_mb: int = 256
    python_sandbox_max_output_bytes: int = 5242880
    python_sandbox_max_code_bytes: int = 1048576
    python_sandbox_allow_network: bool = False

    workspace_root: str = ".dsrt/workspaces"
    workspace_max_file_size_mb: int = 50
    workspace_max_total_size_mb: int = 500

    embedding_provider: str = "local-hash"
    embedding_model_identifier: str = "default"
    embedding_dimensions: int = 384

@lru_cache(maxsize=1)
def get_settings() -> DSRTSettings:
    return DSRTSettings()
