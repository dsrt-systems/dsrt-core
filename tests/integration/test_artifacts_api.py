"""Integration tests for the Artifacts API endpoints."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from core.agents.registry import AgentRegistry
from core.kernel.kernel import ExecutionKernel
from core.repositories import (
    AgentRepository,
    CapabilityRepository,
    EventRepository,
    ExecutionRepository,
    TaskRepository,
)
from core.storage.database import db_manager
from sdk.agent.runtime import build_agent_sdk


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class TestArtifactsAPI:
    async def test_artifacts_api_endpoints(self, auth_client: tuple[AsyncClient, str]):
        client, token = auth_client
        headers = {"Authorization": f"Bearer {token}"}

        cap_slug = _uid("cap")
        agent_slug = _uid("agent")

        # 1) Setup minimal agent and task to get an execution ID
        await client.post(
            "/api/v1/capabilities",
            headers=headers,
            json={"slug": cap_slug, "name": "Cap", "description": "d", "version": "1.0"},
        )
        await client.post(
            "/api/v1/agents/register",
            headers=headers,
            json={
                "manifest": {
                    "identity": {
                        "id": agent_slug,
                        "name": "Agent",
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
                "package_reference": "agents.test",
            },
        )
        task_resp = await client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"agent_slug": agent_slug, "objective": "Make artifacts"},
        )
        task_id = task_resp.json()["id"]
        org_id = task_resp.json()["organization_id"]
        user_id = task_resp.json()["user_id"]

        exe_resp = await client.post(
            f"/api/v1/tasks/{task_id}/execute", headers=headers,
        )
        exe = exe_resp.json()["execution"]
        exe_id = exe["id"]
        agent_version_id = exe["agent_version_id"]

        # 2) Use the SDK factory internally to simulate an agent creating an artifact
        async with db_manager.session() as session:
            task_repo = TaskRepository(session)
            exe_repo = ExecutionRepository(session)
            agent_repo = AgentRepository(session)
            cap_repo = CapabilityRepository(session)
            event_repo = EventRepository(session)
            kernel = ExecutionKernel(task_repo, exe_repo, AgentRegistry(agent_repo, cap_repo), event_repo)
            
            sdk = build_agent_sdk(
                session=session,
                kernel=kernel,
                execution_id=exe_id,
                task_id=task_id,
                organization_id=org_id,
                user_id=user_id,
                agent_slug=agent_slug,
                agent_version="1.0.0",
                agent_version_id=agent_version_id,
            )

            # Create the artifact through the SDK
            artifact_sdk_obj = await sdk.artifacts.create(
                name="test_report.pdf",
                artifact_type="REPORT",
                content=b"fake pdf content",
                mime_type="application/pdf",
                metadata={"pages": 1}
            )
            artifact_id = artifact_sdk_obj.id

        # 3) Test the REST API: List artifacts for execution
        list_resp = await client.get(
            f"/api/v1/executions/{exe_id}/artifacts",
            headers=headers
        )
        assert list_resp.status_code == 200
        list_data = list_resp.json()
        assert list_data["total"] == 1
        assert list_data["artifacts"][0]["id"] == artifact_id
        assert list_data["artifacts"][0]["name"] == "test_report.pdf"
        assert list_data["artifacts"][0]["artifact_type"] == "REPORT"

        # 4) Test the REST API: Get specific artifact
        get_resp = await client.get(
            f"/api/v1/artifacts/{artifact_id}",
            headers=headers
        )
        assert get_resp.status_code == 200
        get_data = get_resp.json()
        assert get_data["id"] == artifact_id
        assert get_data["content_hash"] == artifact_sdk_obj.content_hash
        assert get_data["metadata"]["pages"] == 1