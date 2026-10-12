"""
Phase C2 Golden Test — Seamless Model Switching (C2 §64).

Proves that an agent task can execute on Model A (OpenAI), encounter a mid-task model switch
to Model B (Gemini), and finish successfully with zero lost task state or corrupted context.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

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
from schemas.domain import ExecutionStatus, ProviderType
from sdk.agent import AgentExecutionRequest, AgentInitializationRequest, SDKModelRequest
from sdk.agent.runtime import build_agent_sdk


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class TestC2GoldenPath:
    @patch("core.providers.google.adapter.genai.Client")
    @patch("core.providers.openai.adapter.AsyncOpenAI")
    async def test_c2_model_switching_golden_path(
        self,
        mock_openai_class,
        mock_google_class,
        auth_client: tuple[AsyncClient, str],
    ):
        client, token = auth_client
        headers = {"Authorization": f"Bearer {token}"}
        suffix = uuid.uuid4().hex[:8]

        # -------------------------------------------------------------------
        # Step 1: Register Provider A (OpenAI) & Provider B (Google) + Models
        # -------------------------------------------------------------------
        p_openai = await client.post(
            "/api/v1/providers",
            headers=headers,
            json={"slug": f"openai_{suffix}", "name": "OpenAI", "provider_type": ProviderType.CLOUD.value},
        )
        p_openai_id = p_openai.json()["id"]

        m_openai = await client.post(
            "/api/v1/models",
            headers=headers,
            json={
                "provider_id": p_openai_id,
                "slug": f"gpt4_{suffix}",
                "name": "GPT-4",
                "model_identifier": "gpt-4-0613",
                "version": "1.0",
                "capabilities": {"text_generation": True, "structured_output": True},
                "context_config": {"max_input_tokens": 8192, "max_output_tokens": 4096},
            },
        )
        model_a_id = m_openai.json()["id"]

        p_google = await client.post(
            "/api/v1/providers",
            headers=headers,
            json={"slug": f"google_{suffix}", "name": "Google", "provider_type": ProviderType.CLOUD.value},
        )
        p_google_id = p_google.json()["id"]

        m_google = await client.post(
            "/api/v1/models",
            headers=headers,
            json={
                "provider_id": p_google_id,
                "slug": f"gemini_{suffix}",
                "name": "Gemini 1.5",
                "model_identifier": "gemini-1.5-pro",
                "version": "1.0",
                "capabilities": {"text_generation": True, "structured_output": True},
                "context_config": {"max_input_tokens": 1000000, "max_output_tokens": 8192},
            },
        )
        model_b_id = m_google.json()["id"]

        # -------------------------------------------------------------------
        # Step 2: Register Research Intelligence Agent & Create Task
        # -------------------------------------------------------------------
        async with db_manager.session() as session:
            await register_agent(session)

        task_resp = await client.post(
            "/api/v1/tasks",
            headers=headers,
            json={
                "agent_slug": "research_intelligence",
                "objective": "Research quantum error correction.",
                "input_payload": {
                    "use_model_reasoning": False,
                    "evidence": [
                        {
                            "source_title": "Quantum Journal",
                            "passage": "Surface codes achieve 99.9% fidelity.",
                            "claim": "Surface codes reach threshold.",
                        }
                    ],
                },
            },
        )
        task_id = task_resp.json()["id"]
        org_id = task_resp.json()["organization_id"]
        user_id = task_resp.json()["user_id"]

        exe_resp = await client.post(f"/api/v1/tasks/{task_id}/execute", headers=headers)
        exe_id = exe_resp.json()["execution"]["id"]
        agent_version_id = exe_resp.json()["execution"]["agent_version_id"]

        # -------------------------------------------------------------------
        # Step 3: Setup Mock Responses for Both Models
        # -------------------------------------------------------------------
        # OpenAI Mock
        mock_oai = AsyncMock()
        mock_openai_class.return_value = mock_oai
        mock_oai_choice = AsyncMock()
        mock_oai_choice.message.content = "OpenAI reasoning output."
        mock_oai_choice.message.tool_calls = None
        mock_oai_choice.finish_reason = "stop"
        mock_oai_resp = AsyncMock()
        mock_oai_resp.choices = [mock_oai_choice]
        mock_oai_resp.model = "gpt-4-0613"
        mock_oai_resp.usage.prompt_tokens = 50
        mock_oai_resp.usage.completion_tokens = 20
        mock_oai_resp.usage.total_tokens = 70
        mock_oai.chat.completions.create.return_value = mock_oai_resp

        # Google Mock
        mock_goog = MagicMock()
        mock_google_class.return_value = mock_goog
        mock_goog.aio = AsyncMock()
        mock_g_part = MagicMock()
        mock_g_part.text = "Gemini reasoning output."
        mock_g_part.function_call = None
        mock_g_cand = MagicMock()
        mock_g_cand.content.parts = [mock_g_part]
        mock_g_cand.finish_reason = 1
        mock_g_usage = MagicMock()
        mock_g_usage.prompt_token_count = 60
        mock_g_usage.candidates_token_count = 30
        mock_g_usage.total_token_count = 90
        mock_g_resp = MagicMock()
        mock_g_resp.candidates = [mock_g_cand]
        mock_g_resp.usage_metadata = mock_g_usage
        mock_g_resp.model_version = "gemini-1.5-pro-001"
        mock_goog.aio.models.generate_content.return_value = mock_g_resp

        # -------------------------------------------------------------------
        # Step 4: Execute Call 1 on Model A (OpenAI)
        # -------------------------------------------------------------------
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
            await kernel.transition_execution_status(exe_id, ExecutionStatus.INITIALIZING)
            await kernel.transition_execution_status(exe_id, ExecutionStatus.RUNNING)

            # Call Model A directly via SDK — explicitly overriding to model_a_id (GPT-4)
            resp_a = await sdk.model.generate(
                SDKModelRequest(
                    purpose="step_1",
                    messages=[{"role": "user", "content": "Step 1"}],
                    metadata={"override_model_id": model_a_id},
                )
            )
            assert resp_a.output == "OpenAI reasoning output."

            # -------------------------------------------------------------------
            # Step 5: Execute Call 2 on Model B (Gemini) — MODEL SWITCH MID-TASK
            # -------------------------------------------------------------------
            # Call Model B directly via SDK — ModelGateway detects model mismatch, closes Session 1, opens Session 2
            resp_b = await sdk.model.generate(
                SDKModelRequest(
                    purpose="step_2",
                    messages=[{"role": "user", "content": "Step 2"}],
                    metadata={"override_model_id": model_b_id},
                )
            )
            assert resp_b.output == "Gemini reasoning output."

            # Finalize Agent Execution
            result = await adapter.execute(
                AgentExecutionRequest(
                    execution_id=exe_id,
                    task_id=task_id,
                    objective="Research quantum error correction.",
                    input_payload={
                        "use_model_reasoning": False,
                        "evidence": [
                            {
                                "source_title": "Quantum Journal",
                                "passage": "Surface codes achieve 99.9% fidelity.",
                                "claim": "Surface codes reach threshold.",
                            }
                        ],
                    },
                )
            )
            assert result.status == "COMPLETED"

            # Transition following valid lifecycle: RUNNING -> FINALIZING -> COMPLETED
            await kernel.transition_execution_status(exe_id, ExecutionStatus.FINALIZING)
            await kernel.transition_execution_status(exe_id, ExecutionStatus.COMPLETED)

        # -------------------------------------------------------------------
        # Step 6: Verify Telemetry — Session Switched Event & Checkpoints Present
        # -------------------------------------------------------------------
        tel_resp = await client.get(f"/api/v1/executions/{exe_id}/telemetry", headers=headers)
        assert tel_resp.status_code == 200
        data = tel_resp.json()

        event_types = [e["event_type"] for e in data["events"]]
        assert "MODEL_REQUEST_CREATED" in event_types
        assert "MODEL_SESSION_SWITCHED" in event_types
        assert "MODEL_CHECKPOINT_CREATED" in event_types

        # Verify usage was accumulated across BOTH models
        assert len(data["usage"]) >= 2