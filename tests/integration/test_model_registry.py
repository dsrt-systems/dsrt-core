"""Integration tests for Model Registry API and Service."""

import uuid

import pytest
from httpx import AsyncClient

from schemas.domain.enums import ProviderType


def _unique(s: str) -> str:
    return f"{s}-{uuid.uuid4().hex[:8]}"


class TestModelRegistry:
    async def test_provider_and_model_lifecycle(self, auth_client: tuple[AsyncClient, str]):
        client, token = auth_client
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Register Provider
        prov_slug = _unique("openai")
        p_resp = await client.post(
            "/api/v1/providers",
            headers=headers,
            json={
                "slug": prov_slug,
                "name": "OpenAI",
                "description": "Cloud provider",
                "provider_type": ProviderType.CLOUD.value,
            },
        )
        assert p_resp.status_code == 201, p_resp.text
        prov_id = p_resp.json()["id"]

        # 2. List Providers
        list_p = await client.get("/api/v1/providers", headers=headers)
        assert list_p.status_code == 200
        assert list_p.json()["total"] >= 1

        # 3. Register Model
        model_slug = "gpt-4-test"
        m_resp = await client.post(
            "/api/v1/models",
            headers=headers,
            json={
                "provider_id": prov_id,
                "slug": model_slug,
                "name": "GPT-4 Test",
                "model_identifier": "gpt-4-0613",
                "version": "1.0",
                "capabilities": {
                    "text_generation": True,
                    "tool_calling": True,
                },
                "context_config": {
                    "max_input_tokens": 8192,
                    "max_output_tokens": 4096,
                },
                "pricing_config": {
                    "input_cost_per_m": "30.0",
                    "output_cost_per_m": "60.0",
                },
            },
        )
        assert m_resp.status_code == 201, m_resp.text
        model_id = m_resp.json()["id"]

        # 4. Get Model and Verify Unpacking
        get_m = await client.get(f"/api/v1/models/{model_id}", headers=headers)
        assert get_m.status_code == 200
        data = get_m.json()
        assert data["slug"] == model_slug
        assert data["capabilities"]["tool_calling"] is True
        assert data["context_config"]["max_input_tokens"] == 8192
        assert data["pricing_config"]["input_cost_per_m"] == "30.0"

        # 5. List Models by Provider
        list_m = await client.get(f"/api/v1/models?provider_id={prov_id}", headers=headers)
        assert list_m.status_code == 200
        assert list_m.json()["total"] == 1