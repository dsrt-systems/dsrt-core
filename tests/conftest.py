"""
Shared pytest fixtures for DSRT Core.
"""

from __future__ import annotations

import os
from typing import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Enforce testing environment flag
os.environ["DSRT_TESTING"] = "true"

from core.api.app import create_app
from core.storage.database import db_manager


@pytest_asyncio.fixture(scope="session", autouse=True)
async def initialize_database() -> AsyncIterator[None]:
    """Initialize DB engine once per test session."""
    await db_manager.initialize()
    yield
    await db_manager.shutdown()


@pytest_asyncio.fixture(scope="session")
async def app():
    """Session-scoped FastAPI app instance."""
    return create_app()


@pytest_asyncio.fixture(scope="session")
async def client(app) -> AsyncIterator[AsyncClient]:
    """HTTPX async client bound to the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(scope="session")
async def auth_client(client: AsyncClient) -> tuple[AsyncClient, str]:
    """Register a throwaway user and return (client, bearer_token)."""
    import uuid

    suffix = uuid.uuid4().hex[:10]
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"test-{suffix}@example.com",
            "display_name": "Test User",
            "password": "correct-horse-battery",
            "organization_name": f"Org {suffix}",
            "organization_slug": f"org-{suffix}",
        },
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["token"]["access_token"]
    return client, token