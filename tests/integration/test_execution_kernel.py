"""Integration tests for Task creation, Execution Kernel, and Cancellation."""

from __future__ import annotations

import uuid

from httpx import AsyncClient


def _unique(s: str) -> str:
    return f"{s}_{uuid.uuid4().hex[:8]}"


class TestExecutionKernelIntegration:
    async def test_full_task_and_execution_lifecycle(
        self, auth_client: tuple[AsyncClient, str],
    ):
        client, token = auth_client
        headers = {"Authorization": f"Bearer {token}"}

        cap_slug = _unique("web_search")
        agent_id = _unique("research_agent").replace("-", "_")

        # 1. Register capability
        cap_resp = await client.post(
            "/api/v1/capabilities",
            headers=headers,
            json={
                "slug": cap_slug,
                "name": "Web Search",
                "description": "Web Search",
                "version": "1.0.0",
            },
        )
        assert cap_resp.status_code == 201, cap_resp.text

        # 2. Register agent
        agent_resp = await client.post(
            "/api/v1/agents/register",
            headers=headers,
            json={
                "manifest": {
                    "identity": {
                        "id": agent_id,
                        "name": "Research Agent",
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
                    "permissions": {},
                    "description": "Research agent",
                },
                "package_reference": "agents.research",
            },
        )
        assert agent_resp.status_code == 201, agent_resp.text

        # 3. Create Task
        task_resp = await client.post(
            "/api/v1/tasks",
            headers=headers,
            json={
                "agent_slug": agent_id,
                "objective": "Perform deep research on lithium recycling.",
                "input_payload": {"query": "lithium recycling 2025"},
                "constraints": {"max_duration_seconds": 600},
            },
        )
        assert task_resp.status_code == 201, task_resp.text
        task_data = task_resp.json()
        task_id = task_data["id"]
        assert task_data["status"] == "CREATED"

        # 4. Trigger Execution
        exe_resp = await client.post(
            f"/api/v1/tasks/{task_id}/execute",
            headers=headers,
        )
        assert exe_resp.status_code == 201, exe_resp.text
        exe_data = exe_resp.json()["execution"]
        exe_id = exe_data["id"]
        assert exe_data["status"] == "QUEUED"
        assert len(exe_data["configuration_hash"]) == 64

        # 5. Get Execution
        get_exe = await client.get(
            f"/api/v1/executions/{exe_id}",
            headers=headers,
        )
        assert get_exe.status_code == 200
        assert get_exe.json()["task_id"] == task_id

        # 6. Cancel Execution
        cancel_resp = await client.post(
            f"/api/v1/executions/{exe_id}/cancel",
            headers=headers,
        )
        assert cancel_resp.status_code == 200, cancel_resp.text
        assert cancel_resp.json()["execution"]["status"] == "CANCELLED"