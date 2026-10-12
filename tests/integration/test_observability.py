"""Integration tests for C1.11 Observability & Telemetry APIs."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class TestObservability:
    async def test_middleware_injects_request_id_and_timing(self, client: AsyncClient):
        # Even an unauthenticated 401 should get the headers
        resp = await client.get("/api/v1/auth/me")
        
        assert "X-Request-ID" in resp.headers
        assert resp.headers["X-Request-ID"].startswith("req_")
        assert "X-Process-Time" in resp.headers
        assert float(resp.headers["X-Process-Time"]) > 0

    async def test_telemetry_export(self, auth_client: tuple[AsyncClient, str]):
        client, token = auth_client
        headers = {"Authorization": f"Bearer {token}"}

        cap_slug = _uid("cap")
        agent_slug = _uid("agent")

        # Setup
        await client.post(
            "/api/v1/capabilities",
            headers=headers,
            json={"slug": cap_slug, "name": "C", "description": "D", "version": "1.0"},
        )
        await client.post(
            "/api/v1/agents/register",
            headers=headers,
            json={
                "manifest": {
                    "identity": {
                        "id": agent_slug,
                        "name": "A",
                        "version": "1.0.0",
                        "contract_version": "1.0",
                        "publisher": "dsrt",
                        "category": "test",
                    },
                    "capabilities": [cap_slug],
                    "requirements": {
                        "minimum_core_version": "1.0",
                        "required_capabilities": [],
                        "optional_capabilities": [],
                        "required_tools": [],
                        "optional_tools": [],
                    },
                    "permissions": {},
                },
                "package_reference": "pkg",
            },
        )
        task_resp = await client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"agent_slug": agent_slug, "objective": "telemetry test"},
        )
        task_id = task_resp.json()["id"]

        exe_resp = await client.post(
            f"/api/v1/tasks/{task_id}/execute", headers=headers,
        )
        exe_id = exe_resp.json()["execution"]["id"]

        # Fetch telemetry
        tel_resp = await client.get(f"/api/v1/executions/{exe_id}/telemetry", headers=headers)
        assert tel_resp.status_code == 200
        data = tel_resp.json()

        assert data["execution"]["id"] == exe_id
        assert "configuration_hash" in data
        assert len(data["configuration_hash"]) == 64
        assert isinstance(data["events"], list)
        assert isinstance(data["artifacts"], list)
        assert isinstance(data["usage"], list)
        
        # We expect at least the EXECUTION_CREATED event to exist immediately
        assert len(data["events"]) >= 1
        assert data["events"][0]["event_type"] == "EXECUTION_CREATED"