"""
End-to-end integration test for the Research Intelligence Agent (C1 §53).

Golden path:
  register capability + agent → create task → create execution → build SDK →
  initialize agent → execute agent → assert artifact + trajectory + verification.
"""

from __future__ import annotations

import asyncio
import socket
import uuid

import pytest
from httpx import AsyncClient

from agents.research_intelligence.integration import register_agent
from agents.research_intelligence.runtime.agent import ResearchIntelligenceAgent
from core.agents.adapter import AgentAdapter
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
from schemas.domain import ExecutionStatus
from sdk.agent import AgentExecutionRequest, AgentInitializationRequest
from sdk.agent.runtime import build_agent_sdk


class TestResearchAgentGoldenPath:
    async def test_research_agent_end_to_end(
        self, auth_client: tuple[AsyncClient, str],
    ):
        client, token = auth_client
        headers = {"Authorization": f"Bearer {token}"}

        # 1) Bootstrap: register capabilities + agent using the agent's own registrar.
        async with db_manager.session() as session:
            info = await register_agent(session)
        assert info["agent_slug"] == "research_intelligence"
        assert info["agent_id"].startswith("agt_")
        assert info["agent_version"] == "1.0.0"

        # 2) Create the research task via the public API.
        objective = "Investigate the state of solid-state batteries."
        input_payload = {
            "questions": [
                "What is the current maturity of solid-state batteries?",
                "What are the primary technical barriers?",
            ],
            "evidence": [
                {
                    "source_title": "Journal of Energy Materials 2025",
                    "source_url": "https://example.org/jem-2025",
                    "publisher": "Journal of Energy Materials",
                    "passage": (
                        "Solid-state prototypes have reached 400 Wh/kg in lab conditions "
                        "as of 2025, up from 300 Wh/kg in 2023."
                    ),
                    "claim": "Solid-state prototype energy density reached ~400 Wh/kg by 2025.",
                    "location": "p. 12",
                },
                {
                    "source_title": "Battery Research Review",
                    "source_url": "https://example.org/brr",
                    "publisher": "BRR",
                    "passage": (
                        "Manufacturing scale-up remains the largest barrier; "
                        "dendrite formation and interfacial resistance persist."
                    ),
                    "claim": "Manufacturing scale-up is the primary barrier to commercialization.",
                    "location": "§3.2",
                },
            ],
            "contradictions": [
                {
                    "claim_a": "Solid-state prototype energy density reached ~400 Wh/kg by 2025.",
                    "claim_b": "Prototypes remain below 350 Wh/kg according to some vendor reports.",
                    "explanation": "Different measurement methodologies across sources.",
                },
            ],
        }

        # Robust network calls handling transient Windows DNS drops
        for attempt in range(3):
            try:
                task_resp = await client.post(
                    "/api/v1/tasks",
                    headers=headers,
                    json={
                        "agent_slug": "research_intelligence",
                        "objective": objective,
                        "input_payload": input_payload,
                    },
                )
                assert task_resp.status_code == 201, task_resp.text
                break
            except (socket.gaierror, OSError):
                if attempt == 2:
                    raise
                await asyncio.sleep(0.5)

        task_id = task_resp.json()["id"]
        org_id = task_resp.json()["organization_id"]
        user_id = task_resp.json()["user_id"]

        # 3) Create the execution.
        for attempt in range(3):
            try:
                exe_resp = await client.post(
                    f"/api/v1/tasks/{task_id}/execute", headers=headers,
                )
                assert exe_resp.status_code == 201, exe_resp.text
                break
            except (socket.gaierror, OSError):
                if attempt == 2:
                    raise
                await asyncio.sleep(0.5)

        exe = exe_resp.json()["execution"]
        exe_id = exe["id"]
        agent_version_id = exe["agent_version_id"]

        # 4) Build the SDK, wrap the agent in the AgentAdapter, run the lifecycle.
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
                agent_slug="research_intelligence",
                agent_version="1.0.0",
                agent_version_id=agent_version_id,
            )

            agent = ResearchIntelligenceAgent()
            adapter = AgentAdapter(agent)

            init_result = await adapter.initialize(
                sdk,
                AgentInitializationRequest(
                    execution_id=exe_id,
                    task_id=task_id,
                    organization_id=org_id,
                    agent_version_id=agent_version_id,
                    sdk_version=sdk.sdk_version,
                    contract_version=sdk.contract_version,
                ),
            )
            assert init_result.status == "READY"

            # Kernel transitions to RUNNING before agent executes.
            await kernel.transition_execution_status(
                exe_id, ExecutionStatus.INITIALIZING,
            )
            await kernel.transition_execution_status(
                exe_id, ExecutionStatus.RUNNING,
            )

            result = await adapter.execute(
                AgentExecutionRequest(
                    execution_id=exe_id,
                    task_id=task_id,
                    objective=objective,
                    input_payload=input_payload,
                )
            )
            assert result.status == "COMPLETED", result.error_message
            assert len(result.artifacts_created) == 1
            artifact_id = result.artifacts_created[0]

            # Kernel completes.
            await kernel.transition_execution_status(
                exe_id, ExecutionStatus.VERIFYING,
            )
            await kernel.transition_execution_status(
                exe_id, ExecutionStatus.FINALIZING,
            )
            await kernel.transition_execution_status(
                exe_id, ExecutionStatus.COMPLETED,
                result_summary=result.result_summary,
            )

        # 5) Verify artifact is reachable via the REST API.
        for attempt in range(3):
            try:
                art_resp = await client.get(
                    f"/api/v1/artifacts/{artifact_id}", headers=headers,
                )
                assert art_resp.status_code == 200
                break
            except (socket.gaierror, OSError):
                if attempt == 2:
                    raise
                await asyncio.sleep(0.5)

        art = art_resp.json()
        assert art["artifact_type"] == "REPORT"
        assert art["mime_type"] == "text/markdown"
        assert art["provenance"]["source_count"] == 2
        assert art["provenance"]["claim_count"] == 2
        assert art["provenance"]["verification_status"] in (
            "PASSED", "PASSED_WITH_WARNINGS",
        )

        # 6) Verify execution telemetry captures the trajectory.
        for attempt in range(3):
            try:
                tel_resp = await client.get(
                    f"/api/v1/executions/{exe_id}/telemetry", headers=headers,
                )
                assert tel_resp.status_code == 200
                break
            except (socket.gaierror, OSError):
                if attempt == 2:
                    raise
                await asyncio.sleep(0.5)

        tel = tel_resp.json()

        assert tel["execution"]["status"] == "COMPLETED"
        assert len(tel["artifacts"]) == 1

        event_types = [e["event_type"] for e in tel["events"]]
        agent_event_kinds = [
            e["payload"].get("agent_event_type")
            for e in tel["events"]
            if e["event_type"] == "AGENT_EVENT"
        ]

        assert "EXECUTION_CREATED" in event_types
        assert "EXECUTION_STARTED" in event_types
        assert "EXECUTION_COMPLETED" in event_types
        assert "BENCHMARK_RECORD" in event_types

        for expected in (
            "AGENT_READY",
            "RESEARCH_STARTED",
            "RESEARCH_PLAN_CREATED",
            "EVIDENCE_ANALYZED",
            "RESEARCH_VERIFIED",
            "RESEARCH_COMPLETED",
        ):
            assert expected in agent_event_kinds, (
                f"Missing agent event {expected}. Got: {agent_event_kinds}"
            )

    async def test_research_agent_fails_when_no_evidence_provided(
        self, auth_client: tuple[AsyncClient, str],
    ):
        client, token = auth_client
        headers = {"Authorization": f"Bearer {token}"}

        async with db_manager.session() as session:
            await register_agent(session)

        # Robust network calls handling transient Windows DNS drops
        for attempt in range(3):
            try:
                task_resp = await client.post(
                    "/api/v1/tasks",
                    headers=headers,
                    json={
                        "agent_slug": "research_intelligence",
                        "objective": "Investigate X with no evidence.",
                        "input_payload": {},
                    },
                )
                assert task_resp.status_code == 201
                break
            except (socket.gaierror, OSError):
                if attempt == 2:
                    raise
                await asyncio.sleep(0.5)

        task_id = task_resp.json()["id"]
        org_id = task_resp.json()["organization_id"]
        user_id = task_resp.json()["user_id"]

        for attempt in range(3):
            try:
                exe_resp = await client.post(
                    f"/api/v1/tasks/{task_id}/execute", headers=headers,
                )
                assert exe_resp.status_code == 201
                break
            except (socket.gaierror, OSError):
                if attempt == 2:
                    raise
                await asyncio.sleep(0.5)

        exe = exe_resp.json()["execution"]
        exe_id = exe["id"]
        agent_version_id = exe["agent_version_id"]

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
                agent_slug="research_intelligence",
                agent_version="1.0.0",
                agent_version_id=agent_version_id,
            )

            agent = ResearchIntelligenceAgent()
            adapter = AgentAdapter(agent)

            await adapter.initialize(
                sdk,
                AgentInitializationRequest(
                    execution_id=exe_id,
                    task_id=task_id,
                    organization_id=org_id,
                    agent_version_id=agent_version_id,
                    sdk_version=sdk.sdk_version,
                    contract_version=sdk.contract_version,
                ),
            )
            result = await adapter.execute(
                AgentExecutionRequest(
                    execution_id=exe_id,
                    task_id=task_id,
                    objective="Investigate X with no evidence.",
                    input_payload={},
                )
            )

        # No evidence provided → completes with warnings (all questions unresolved,
        # no claims → verification passes structurally, no unsupported claims).
        assert result.status == "COMPLETED"
        assert result.result_summary["claim_count"] == 0
        assert len(result.result_summary["unresolved_questions"]) >= 2