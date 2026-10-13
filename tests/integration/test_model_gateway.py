"""
Integration tests for ModelGateway (C2.11).

Tests end-to-end Model Fabric execution, session management, routing,
metering, and event stream telemetry.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from core.models.gateway import ModelGateway
from core.storage.database import db_manager
from schemas.domain import (
    MessageRole,
    ModelMessage,
    ModelPolicy,
    ModelRequest,
    ProviderType,
)


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class TestModelGatewayIntegration:
    @patch("core.providers.openai.adapter.OpenAIAdapter._get_client")
    async def test_gateway_end_to_end_execution(
        self, mock_openai_get_client, auth_client: tuple[AsyncClient, str]
    ):
        client, token = auth_client
        headers = {"Authorization": f"Bearer {token}"}
        suffix = uuid.uuid4().hex[:8]

        # 1. Register Provider & Model
        p_resp = await client.post(
            "/api/v1/providers",
            headers=headers,
            json={
                "slug": f"openai_{suffix}",
                "name": "OpenAI",
                "provider_type": ProviderType.CLOUD.value,
            },
        )
        prov_id = p_resp.json()["id"]

        m_resp = await client.post(
            "/api/v1/models",
            headers=headers,
            json={
                "provider_id": prov_id,
                "slug": f"gpt4_{suffix}",
                "name": "GPT-4",
                "model_identifier": "gpt-4-0613",
                "version": "1.0",
                "capabilities": {"text_generation": True},
                "context_config": {"max_input_tokens": 8192, "max_output_tokens": 4096},
                "pricing_config": {"input_cost_per_m": "10.0", "output_cost_per_m": "30.0"},
            },
        )
        model_id = m_resp.json()["id"]

        # 2. Setup Task & Execution via REST
        cap_resp = await client.post(
            "/api/v1/capabilities",
            headers=headers,
            json={"slug": f"cap_{suffix}", "name": "Cap", "description": "D", "version": "1.0.0"},
        )
        cap_slug = cap_resp.json()["slug"]

        agent_slug = f"agent_{suffix}"
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
                        "minimum_core_version": "1.0.0",
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
            json={"agent_slug": agent_slug, "objective": "Gateway test"},
        )
        task_data = task_resp.json()
        task_id = task_data["id"]
        org_id = task_data["organization_id"]

        exe_resp = await client.post(f"/api/v1/tasks/{task_id}/execute", headers=headers)
        exe_id = exe_resp.json()["execution"]["id"]

        # 3. Setup mock OpenAI response
        mock_client = AsyncMock()
        mock_openai_get_client.return_value = mock_client
        mock_choice = AsyncMock()
        mock_choice.message.content = "Model Gateway response."
        mock_choice.message.tool_calls = None
        mock_choice.finish_reason = "stop"
        mock_response = AsyncMock()
        mock_response.choices = [mock_choice]
        mock_response.model = "gpt-4-0613"
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response.usage.total_tokens = 150
        mock_client.chat.completions.create.return_value = mock_response

        # 4. Invoke ModelGateway directly with policy restricted to this test's model
        async with db_manager.session() as session:
            gateway = ModelGateway(session)

            req = ModelRequest(
                request_id=_uid("req"),
                execution_id=exe_id,
                task_id=task_id,
                organization_id=org_id,
                purpose="synthesis",
                messages=[ModelMessage(role=MessageRole.USER, content="Synthesize data")],
                model_policy=ModelPolicy(allowed_models=[model_id]),
            )

            response = await gateway.execute_request(req, override_api_key="sk-test-key")

            assert response.output == "Model Gateway response."
            assert response.usage.total_tokens == 150

        # 5. Verify Telemetry via REST API
        tel_resp = await client.get(f"/api/v1/executions/{exe_id}/telemetry", headers=headers)
        assert tel_resp.status_code == 200
        data = tel_resp.json()

        event_types = [e["event_type"] for e in data["events"]]
        assert "MODEL_REQUEST_CREATED" in event_types
        assert "MODEL_ROUTING_STARTED" in event_types
        assert "MODEL_ROUTING_COMPLETED" in event_types
        assert "MODEL_REQUEST_STARTED" in event_types
        assert "MODEL_CHECKPOINT_CREATED" in event_types
        assert "MODEL_REQUEST_COMPLETED" in event_types

        # Verify usage was recorded and aggregated
        assert len(data["usage"]) == 1
        assert data["usage"][0]["total_tokens"] == 150