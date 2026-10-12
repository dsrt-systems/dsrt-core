"""
DSRT Core — Health Check Verification.
"""

from __future__ import annotations

from httpx import AsyncClient

from core.version import AGENT_CONTRACT_VERSION, CORE_VERSION


class TestHealthCheck:
    async def test_health_endpoint_returns_200(self, client: AsyncClient):
        response = await client.get("/health")
        assert response.status_code == 200

    async def test_health_reports_correct_version(self, client: AsyncClient):
        response = await client.get("/health")
        data = response.json()
        assert data["core_version"] == CORE_VERSION
        assert data["agent_contract_version"] == AGENT_CONTRACT_VERSION
        assert data["status"] == "healthy"
        assert data["components"]["database"] == "healthy"

    async def test_root_endpoint_returns_system_identity(self, client: AsyncClient):
        response = await client.get("/")
        data = response.json()
        assert data["system"] == "DSRT Core"
        assert data["version"] == CORE_VERSION
        assert data["status"] == "operational"