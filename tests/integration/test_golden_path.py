"""
DSRT Core Golden Path — C1 §53.

Executes the complete canonical C1 pipeline PURELY through the REST API + the
public SDK, asserting every checkpoint from C1 §63 Definition of Done.

Pipeline:
    User → Create Task → Select Agent → Create Execution →
    Initialize Agent → Build Context → Agent produces evidence →
    Verification → Artifact → Events persist → Execution Completed →
    Telemetry Recorded.
"""

from __future__ import annotations

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
from core.version import AGENT_CONTRACT_VERSION, CORE_VERSION, SDK_VERSION
from schemas.domain import ExecutionStatus
from sdk.agent import AgentExecutionRequest, AgentInitializationRequest
from sdk.agent.runtime import build_agent_sdk


class TestGoldenPath:
    async def test_c1_golden_path_end_to_end(
        self, auth_client: tuple[AsyncClient, str],
    ):
        client, token = auth_client
        headers = {"Authorization": f"Bearer {token}"}

        # ---------------------------------------------------------------
        # Checkpoint 0: Core is healthy and reports correct versions
        # ---------------------------------------------------------------
        h = await client.get("/health")
        assert h.status_code == 200
        assert h.json()["core_version"] == CORE_VERSION
        assert h.json()["agent_contract_version"] == AGENT_CONTRACT_VERSION
        assert h.json()["components"]["database"] == "healthy"

        # ---------------------------------------------------------------
        # Checkpoint 1: User is authenticated (via fixture) — /auth/me works
        # ---------------------------------------------------------------
        me = await client.get("/api/v1/auth/me", headers=headers)
        assert me.status_code == 200
        me_body = me.json()
        assert me_body["active_organization_id"] is not None

        # ---------------------------------------------------------------
        # Checkpoint 2: Agent + Capabilities registered
        # ---------------------------------------------------------------
        async with db_manager.session() as session:
            reg_info = await register_agent(session)
        assert reg_info["agent_slug"] == "research_intelligence"
        assert reg_info["agent_id"].startswith("agt_")
        assert reg_info["agent_version"] == "1.0.0"

        # Verify via REST API
        agent_resp = await client.get(
            "/api/v1/agents/research_intelligence", headers=headers,
        )
        assert agent_resp.status_code == 200
        assert agent_resp.json()["agent"]["slug"] == "research_intelligence"

        # ---------------------------------------------------------------
        # Checkpoint 3: Create Task with structured input
        # ---------------------------------------------------------------
        objective = "Assess the current state of X in 2025."
        input_payload = {
            "questions": [
                "What is the current state of X?",
                "What are the primary drivers of change in X?",
            ],
            "evidence": [
                {
                    "source_title": "Journal A",
                    "source_url": "https://example.org/a",
                    "publisher": "Journal A",
                    "passage": "X reached maturity in Q3 2025 based on peer-reviewed reports.",
                    "claim": "X reached maturity in 2025.",
                    "location": "p.42",
                },
                {
                    "source_title": "Analyst Report B",
                    "source_url": "https://example.org/b",
                    "publisher": "Analyst B",
                    "passage": "Investment flows into X grew 40% year-over-year.",
                    "claim": "Investment flows into X grew 40% YoY.",
                    "location": "§2",
                },
            ],
        }

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
        task = task_resp.json()
        task_id = task["id"]
        org_id = task["organization_id"]
        user_id = task["user_id"]
        assert task["status"] == "CREATED"

        # ---------------------------------------------------------------
        # Checkpoint 4: Create Execution (Kernel resolves agent + config hash)
        # ---------------------------------------------------------------
        exe_resp = await client.post(
            f"/api/v1/tasks/{task_id}/execute", headers=headers,
        )
        assert exe_resp.status_code == 201, exe_resp.text
        exe = exe_resp.json()["execution"]
        exe_id = exe["id"]
        agent_version_id = exe["agent_version_id"]

        # Core version fingerprint recorded (C1 §39)
        assert exe["core_version"] == CORE_VERSION
        assert exe["contract_version"] == AGENT_CONTRACT_VERSION
        assert len(exe["configuration_hash"]) == 64
        assert exe["status"] == "QUEUED"
        assert exe["resource_limits"]["max_duration_seconds"] > 0

        # ---------------------------------------------------------------
        # Checkpoint 5: Initialize Agent + Execute (through AgentAdapter)
        # ---------------------------------------------------------------
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

            # SDK version stamps are correct (C1 §17)
            assert sdk.sdk_version == SDK_VERSION
            assert sdk.contract_version == AGENT_CONTRACT_VERSION

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

            # Kernel drives execution through the state machine
            await kernel.transition_execution_status(
                exe_id, ExecutionStatus.INITIALIZING,
            )
            await kernel.transition_execution_status(
                exe_id, ExecutionStatus.RUNNING,
            )

            exec_result = await adapter.execute(
                AgentExecutionRequest(
                    execution_id=exe_id,
                    task_id=task_id,
                    objective=objective,
                    input_payload=input_payload,
                )
            )
            assert exec_result.status == "COMPLETED", exec_result.error_message
            assert len(exec_result.artifacts_created) == 1
            artifact_id = exec_result.artifacts_created[0]

            await kernel.transition_execution_status(
                exe_id, ExecutionStatus.VERIFYING,
            )
            await kernel.transition_execution_status(
                exe_id, ExecutionStatus.FINALIZING,
            )
            await kernel.transition_execution_status(
                exe_id,
                ExecutionStatus.COMPLETED,
                result_summary=exec_result.result_summary,
            )

        # Agent health after execution
        health = await agent.health()
        assert health.status == "healthy"

        # ---------------------------------------------------------------
        # Checkpoint 6: Artifact persisted and retrievable (C1 §25)
        # ---------------------------------------------------------------
        art_resp = await client.get(
            f"/api/v1/artifacts/{artifact_id}", headers=headers,
        )
        assert art_resp.status_code == 200
        art = art_resp.json()
        assert art["artifact_type"] == "REPORT"
        assert art["mime_type"] == "text/markdown"
        assert art["execution_id"] == exe_id
        assert art["task_id"] == task_id
        assert art["organization_id"] == org_id
        assert art["size_bytes"] > 0
        assert len(art["content_hash"]) == 64  # SHA-256
        # Provenance recorded (C1 §39)
        assert art["provenance"]["agent_slug"] == "research_intelligence"
        assert art["provenance"]["source_count"] == 2
        assert art["provenance"]["claim_count"] == 2

        # Artifacts listed for execution
        arts_resp = await client.get(
            f"/api/v1/executions/{exe_id}/artifacts", headers=headers,
        )
        assert arts_resp.status_code == 200
        assert arts_resp.json()["total"] == 1

        # ---------------------------------------------------------------
        # Checkpoint 7: Events persist with monotonic sequence (C1 §31)
        # ---------------------------------------------------------------
        events_resp = await client.get(
            f"/api/v1/executions/{exe_id}/events", headers=headers,
        )
        assert events_resp.status_code == 200
        events = events_resp.json()["events"]
        sequences = [e["sequence"] for e in events]
        assert sequences == sorted(sequences), "Events must be monotonically ordered."
        assert sequences[0] == 1

        event_types = [e["event_type"] for e in events]
        for required_event in (
            "EXECUTION_CREATED",
            "EXECUTION_STARTED",
            "EXECUTION_COMPLETED",
            "AGENT_EVENT",
            "BENCHMARK_RECORD",
        ):
            assert required_event in event_types, (
                f"Missing required event: {required_event}"
            )

        # Agent domain events preserved (C1 §24)
        agent_event_kinds = [
            e["payload"].get("agent_event_type")
            for e in events
            if e["event_type"] == "AGENT_EVENT"
        ]
        for kind in (
            "AGENT_READY",
            "RESEARCH_STARTED",
            "RESEARCH_PLAN_CREATED",
            "EVIDENCE_ANALYZED",
            "RESEARCH_VERIFIED",
            "RESEARCH_COMPLETED",
        ):
            assert kind in agent_event_kinds, f"Missing agent event: {kind}"

        # ---------------------------------------------------------------
        # Checkpoint 8: Execution reached COMPLETED terminal state
        # ---------------------------------------------------------------
        exe_final = await client.get(
            f"/api/v1/executions/{exe_id}", headers=headers,
        )
        assert exe_final.status_code == 200
        assert exe_final.json()["status"] == "COMPLETED"
        assert exe_final.json()["completed_at"] is not None
        assert exe_final.json()["error"] is None

        # ---------------------------------------------------------------
        # Checkpoint 9: Telemetry export contains full trajectory (C1 §39-40)
        # ---------------------------------------------------------------
        tel_resp = await client.get(
            f"/api/v1/executions/{exe_id}/telemetry", headers=headers,
        )
        assert tel_resp.status_code == 200
        tel = tel_resp.json()
        assert tel["execution"]["id"] == exe_id
        assert tel["configuration_hash"] == exe["configuration_hash"]
        assert len(tel["events"]) >= 5
        assert len(tel["artifacts"]) == 1
        assert isinstance(tel["usage"], list)

    async def test_cancellation_propagates_end_to_end(
        self, auth_client: tuple[AsyncClient, str],
    ):
        """C1 §34: cancellation must reach a terminal CANCELLED state."""
        client, token = auth_client
        headers = {"Authorization": f"Bearer {token}"}

        async with db_manager.session() as session:
            await register_agent(session)

        task_resp = await client.post(
            "/api/v1/tasks",
            headers=headers,
            json={
                "agent_slug": "research_intelligence",
                "objective": "Cancel test",
                "input_payload": {},
            },
        )
        task_id = task_resp.json()["id"]

        exe_resp = await client.post(
            f"/api/v1/tasks/{task_id}/execute", headers=headers,
        )
        exe_id = exe_resp.json()["execution"]["id"]

        # User cancels the execution
        cancel_resp = await client.post(
            f"/api/v1/executions/{exe_id}/cancel", headers=headers,
        )
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["execution"]["status"] == "CANCELLED"

        # Cancelling again is idempotent
        cancel_again = await client.post(
            f"/api/v1/executions/{exe_id}/cancel", headers=headers,
        )
        assert cancel_again.status_code == 200
        assert cancel_again.json()["execution"]["status"] == "CANCELLED"

        # Trajectory records the cancellation event
        events_resp = await client.get(
            f"/api/v1/executions/{exe_id}/events", headers=headers,
        )
        event_types = [e["event_type"] for e in events_resp.json()["events"]]
        assert "EXECUTION_CANCELLED" in event_types