"""
Database integration tests — verify the C1 schema is deployed on Supabase.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

from core.config import get_settings
from core.storage.database import db_manager
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models import Organization, Task


class TestDatabaseIntegration:
    async def test_database_connects(self):
        healthy = await db_manager.health_check()
        assert healthy is True, "Database health check failed"

    async def test_dsrt_schema_exists(self):
        settings = get_settings()
        async with db_manager.session() as session:
            result = await session.execute(
                text(
                    "SELECT schema_name FROM information_schema.schemata "
                    "WHERE schema_name = :schema"
                ),
                {"schema": settings.database_schema},
            )
            assert result.scalar() == settings.database_schema

    async def test_all_c1_tables_exist(self):
        settings = get_settings()
        expected_tables = {
            "organizations",
            "users",
            "organization_members",
            "capabilities",
            "agents",
            "agent_versions",
            "agent_capabilities",
            "providers",
            "models",
            "tasks",
            "executions",
            "execution_events",
            "artifacts",
            "verification_runs",
            "verification_results",
            "usage_records",
        }

        async with db_manager.session() as session:
            result = await session.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = :schema"
                ),
                {"schema": settings.database_schema},
            )
            tables = {row[0] for row in result.fetchall()}

        missing = expected_tables - tables
        assert not missing, f"Missing tables in dsrt schema: {missing}"

    async def test_can_insert_and_retrieve_organization(self):
        slug = f"test-org-{uuid.uuid4().hex[:10]}"
        org_id: str | None = None

        try:
            async with db_manager.session() as session:
                org = Organization(name="Test Org", slug=slug)
                session.add(org)
                await session.flush()
                org_id = org.id
                assert org_id.startswith("org_")
                assert org.created_at is not None

            async with db_manager.session() as session:
                result = await session.execute(
                    select(Organization).where(Organization.id == org_id)
                )
                retrieved = result.scalar_one_or_none()
                assert retrieved is not None
                assert retrieved.slug == slug
                assert retrieved.status == "active"
        finally:
            if org_id:
                try:
                    async with db_manager.session() as session:
                        await session.execute(
                            delete(Organization).where(Organization.id == org_id)
                        )
                except Exception:
                    pass

    async def test_foreign_keys_enforced(self):
        with pytest.raises(IntegrityError):
            async with db_manager.session() as session:
                task = Task(
                    organization_id=new_id(IdPrefix.ORGANIZATION),
                    user_id=new_id(IdPrefix.USER),
                    agent_slug="test_agent",
                    objective="Test",
                )
                session.add(task)
                await session.flush()

    async def test_pgvector_extension_available(self):
        async with db_manager.session() as session:
            result = await session.execute(
                text(
                    "SELECT extname FROM pg_extension WHERE extname = 'vector'"
                )
            )
            assert result.scalar() == "vector", "pgvector extension not enabled"