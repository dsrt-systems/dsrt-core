"""
Alembic environment configuration for DSRT Core (Supabase).

Uses async engine and the DEDICATED migration URL (direct connection, not pooled).
Scopes migrations to the `dsrt` schema.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from core.config import get_settings
from core.storage.database import Base, DSRT_SCHEMA_NAME
import core.storage.models  # noqa: F401  — registers models with Base.metadata


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.async_migration_url)

target_metadata = Base.metadata


def _include_object(object, name, type_, reflected, compare_to):  # noqa: ANN001
    """Only manage objects that live in the DSRT schema."""
    if type_ == "table":
        return object.schema == DSRT_SCHEMA_NAME
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_schemas=True,
        include_object=_include_object,
        version_table_schema=DSRT_SCHEMA_NAME,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations synchronously on the connection."""
    # 1. Ensure the DSRT schema exists
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {DSRT_SCHEMA_NAME}"))
    connection.commit()

    # 2. Configure Alembic context
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_schemas=True,
        include_object=_include_object,
        version_table_schema=DSRT_SCHEMA_NAME,
    )

    # 3. Execute migrations inside a explicit transaction and COMMIT IT
    with context.begin_transaction():
        context.run_migrations()
    
    connection.commit()


async def run_async_migrations() -> None:
    """Create async engine and run migrations with explicit commit."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
        },
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
        await connection.commit()

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()