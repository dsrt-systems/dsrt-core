"""
DSRT Core Configuration

Central configuration loaded from environment variables.
All DSRT subsystems read configuration from this module.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_ACCEPTED_DB_SCHEMES = ("postgresql://", "postgres://")
_PLACEHOLDER_MARKERS = ("YOUR_PROJECT_REF", "YOUR_PASSWORD", "YOUR_REGION")


def _normalize_to_asyncpg(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    raise ValueError(
        f"Cannot normalize database URL — unsupported scheme in: {url[:40]}..."
    )


class DSRTSettings(BaseSettings):
    """DSRT Core configuration derived from environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="DSRT_",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Core Identity ---
    core_version: str = "1.0.0"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    testing: bool = False

    # --- API ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 1
    api_reload: bool = False

    # --- Database (Supabase) ---
    database_schema: str = "dsrt"
    database_url: str = Field(
        ...,
        description="Application connection URL (Supabase Session Pooler).",
    )
    database_migration_url: str = Field(
        ...,
        description="Migration connection URL (Supabase Direct Connection).",
    )
    database_pool_min: int = 2
    database_pool_max: int = 10

    @field_validator("database_url", "database_migration_url")
    @classmethod
    def _validate_database_url(cls, v: str) -> str:
        if not v:
            raise ValueError("Database URL is empty.")
        if any(marker in v for marker in _PLACEHOLDER_MARKERS):
            raise ValueError("Database URL contains unconfigured placeholder markers.")
        if not v.startswith(_ACCEPTED_DB_SCHEMES) and not v.startswith("postgresql+asyncpg://"):
            raise ValueError("Database URL must start with 'postgresql://' or 'postgres://'")
        return v

    @property
    def async_database_url(self) -> str:
        return _normalize_to_asyncpg(self.database_url)

    @property
    def async_migration_url(self) -> str:
        return _normalize_to_asyncpg(self.database_migration_url)

    # --- Supabase API ---
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""

    # --- Redis ---
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    # --- Security ---
    secret_key: str = "dsrt-dev-secret-key-change-in-production-must-be-at-least-32-chars"
    access_token_expire_minutes: int = 60
    algorithm: str = "HS256"

    @field_validator("secret_key")
    @classmethod
    def _validate_secret_key(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("DSRT_SECRET_KEY must be at least 32 characters.")
        return v

    # --- Storage ---
    storage_type: Literal["local", "s3", "supabase"] = "local"
    storage_local_path: str = "./storage"

    # --- Observability ---
    log_level: str = "DEBUG"
    log_format: Literal["json", "console"] = "json"
    structured_logging: bool = True

    # --- Workspace (C3.8 Filesystem Runtime) ---
    workspace_root: str = Field(
        default="./workspace",
        description="Root directory for isolated execution workspaces.",
    )
    workspace_max_file_size_mb: int = Field(
        default=50,
        description="Maximum size of a single file in the workspace (MB).",
    )
    workspace_max_total_size_mb: int = Field(
        default=500,
        description="Maximum total size of an execution workspace (MB).",
    )

    # --- Python Sandbox (C3.9) ---
    python_sandbox_max_runtime_seconds: int = Field(
        default=60,
        description="Maximum wall-clock runtime for a sandboxed Python execution.",
    )
    python_sandbox_max_memory_mb: int = Field(
        default=512,
        description="Maximum memory a sandboxed Python process can use (POSIX only).",
    )
    python_sandbox_max_output_bytes: int = Field(
        default=5 * 1024 * 1024,
        description="Maximum bytes of combined stdout+stderr captured.",
    )
    python_sandbox_max_code_bytes: int = Field(
        default=256 * 1024,
        description="Maximum size of user code accepted by the sandbox.",
    )
    python_sandbox_allow_network: bool = Field(
        default=False,
        description="Whether sandboxed Python may access the network.",
    )

    # --- Embeddings (C4.5) ---
    embedding_provider: str = Field(
        default="local-hash",
        description=(
            "Embedding provider strategy. "
            "'local-hash' for testing (no API key needed). "
            "'openai' for OpenAI text-embedding-3-small. "
            "Any registered provider slug for BYOK embeddings."
        ),
    )
    embedding_model_identifier: str = Field(
        default="text-embedding-3-small",
        description="Model identifier passed to the provider adapter for embedding generation.",
    )
    embedding_dimensions: int = Field(
        default=384,
        description="Embedding vector dimensions. 384 for local-hash, 1536 for OpenAI text-embedding-3-small.",
    )

    # --- Resource Limits (defaults) ---
    default_execution_timeout_seconds: int = 1800
    default_max_model_calls: int = 100
    default_max_tool_calls: int = 500
    default_max_storage_mb: int = 500


@lru_cache(maxsize=1)
def get_settings() -> DSRTSettings:
    return DSRTSettings()