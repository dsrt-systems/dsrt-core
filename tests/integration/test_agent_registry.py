"""Integration tests for Capability Registry and Agent Registry."""

from __future__ import annotations

import uuid

from httpx import AsyncClient


def _unique(s: str) -> str:
    return f"{s}_{uuid.uuid4().hex[:8]}"


class TestAgentAndCapabilityRegistry:
    async def test_capability_lifecycle(self, auth_client: tuple[AsyncClient, str]):
        client, token = auth_client
        headers = {"Authorization": f"Bearer {token}"}
        slug = _unique("cap")

        resp = await client.post(
            "/api/v1/capabilities",
            headers=headers,
            json={
                "slug": slug,
                "name": "Test Capability",
                "description": "A test capability",
                "version": "1.0.0",
                "risk_level": "low",
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["slug"] == slug

        resp = await client.get("/api/v1/capabilities", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

        resp = await client.get(f"/api/v1/capabilities/{slug}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test Capability"

    async def test_agent_registration_flow(self, auth_client: tuple[AsyncClient, str]):
        client, token = auth_client
        headers = {"Authorization": f"Bearer {token}"}
        cap_slug = _unique("research_planning")
        agent_id = _unique("research_intelligence").replace("-", "_")

        # Register capability first
        cap_resp = await client.post(
            "/api/v1/capabilities",
            headers=headers,
            json={
                "slug": cap_slug,
                "name": "Research Planning",
                "description": "Planning",
                "version": "1.0.0",
            },
        )
        assert cap_resp.status_code == 201, cap_resp.text

        # Register agent
        manifest = {
            "manifest": {
                "identity": {
                    "id": agent_id,
                    "name": "Research Intelligence Agent",
                    "version": "1.0.0",
                    "contract_version": "1.0",
                    "publisher": "dsrt",
                    "category": "research",
                },
                "capabilities": [cap_slug],
                "requirements": {
                    "minimum_core_version": "1.0.0",
                    "required_capabilities": [],
                    "optional_capabilities": [],
                    "required_tools": [],
                    "optional_tools": [],
                },
                "permissions": {
                    "network": {"required": True},
                    "filesystem": {"access": "workspace"},
                },
                "description": "Professional research intelligence package.",
            },
            "package_reference": "agents.research_intelligence",
        }

        reg_agent = await client.post(
            "/api/v1/agents/register",
            headers=headers,
            json=manifest,
        )
        assert reg_agent.status_code == 201, reg_agent.text
        assert reg_agent.json()["manifest"]["identity"]["id"] == agent_id

        # Get agent detail
        get_agent = await client.get(
            f"/api/v1/agents/{agent_id}",
            headers=headers,
        )
        assert get_agent.status_code == 200, get_agent.text
        assert get_agent.json()["agent"]["name"] == "Research Intelligence Agent"

        # Duplicate registration fails
        dup = await client.post(
            "/api/v1/agents/register",
            headers=headers,
            json=manifest,
        )
        assert dup.status_code == 409