"""Integration test: build an SDK against a real Kernel + database."""

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


class TestSDKFactory:
    async def test_sdk_wired_end_to_end(self, auth_client: tuple[AsyncClient, str]):
        client, token = auth_client
        headers = {"Authorization": f"Bearer {token}"}

        cap_slug = _uid("cap")
        agent_slug = _uid("agent")

        # 1) Register capability + agent
        await client.post(
            "/api/v1/capabilities",
            headers=headers,
            json={
                "slug": cap_slug,
                "name": "Cap",
                "description": "d",
                "version": "1.0.0",
            },
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
                        "minimum_core_version": "1.0.0",
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

        # 2) Create task + execution
        task_resp = await client.post(
            "/api/v1/tasks",
            headers=headers,
            json={
                "agent_slug": agent_slug,
                "objective": "Build SDK for me",
                "input_payload": {"key": "value"},
            },
        )
        task_id = task_resp.json()["id"]
        org_id = task_resp.json()["organization_id"]
        user_id = task_resp.json()["user_id"]

        exe_resp = await client.post(
            f"/api/v1/tasks/{task_id}/execute",
            headers=headers,
        )
        exe = exe_resp.json()["execution"]
        exe_id = exe["id"]
        agent_version_id = exe["agent_version_id"]

        # 3) Build a real SDK against a real session
        async with db_manager.session() as session:
            task_repo = TaskRepository(session)
            exe_repo = ExecutionRepository(session)
            agent_repo = AgentRepository(session)
            cap_repo = CapabilityRepository(session)
            event_repo = EventRepository(session)
            registry = AgentRegistry(agent_repo, cap_repo)
            kernel = ExecutionKernel(
                task_repo=task_repo,
                execution_repo=exe_repo,
                agent_registry=registry,
                event_repo=event_repo,
            )

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

            # 4) Context works
            ctx = await sdk.context.get()
            assert ctx.execution_id == exe_id
            assert ctx.task_id == task_id
            assert ctx.objective == "Build SDK for me"
            assert ctx.input_payload == {"key": "value"}
            assert len(ctx.configuration_hash) == 64

            # 5) State works
            await sdk.state.set("counter", 1)
            assert await sdk.state.get("counter") == 1

            # 6) Events emit into the trajectory
            await sdk.events.emit(
                "TEST_EVENT", {"note": "hello from sdk"},
            )

            # 7) Artifact create works
            artifact = await sdk.artifacts.create(
                name="hello.txt",
                artifact_type="TEXT",
                content="hello world",
                mime_type="text/plain",
            )
            assert artifact.id.startswith("art_")
            assert artifact.size_bytes == len("hello world")

            fetched = await sdk.artifacts.get(artifact.id)
            assert fetched is not None
            assert fetched.name == "hello.txt"

            # 8) Verification stub records a run
            v = await sdk.verification.verify(
                subject_id=artifact.id, policy_id="test_policy_v1",
            )
            assert v.status == "INCONCLUSIVE"

            # 9) Tool call is denied at C1
            tool_result = await sdk.tools.call("web.search", {"query": "x"})
            assert tool_result.status == "DENIED"

            # 10) SDK version stamps are correct
            assert sdk.sdk_version == "1.0.0"
            assert sdk.contract_version == "1.0"

        # 11) Trajectory contains our AGENT_EVENT
        events_resp = await client.get(
            f"/api/v1/executions/{exe_id}/events",
            headers=headers,
        )
        assert events_resp.status_code == 200
        events = events_resp.json()["events"]
        agent_events = [e for e in events if e["event_type"] == "AGENT_EVENT"]
        assert len(agent_events) >= 1
        assert agent_events[0]["source"] == f"agent.{agent_slug}"
        assert (
            agent_events[0]["payload"]["agent_event_type"] == "TEST_EVENT"
        )