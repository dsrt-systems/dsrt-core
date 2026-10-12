"""Integration tests for Credential Manager & API."""

import uuid

import pytest
from httpx import AsyncClient

from schemas.domain.enums import ProviderType


def _unique(s: str) -> str:
    return f"{s}-{uuid.uuid4().hex[:8]}"


class TestCredentialsAPI:
    async def test_credential_lifecycle(self, auth_client: tuple[AsyncClient, str]):
        client, token = auth_client
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Register a provider first with a unique slug to prevent collisions
        prov_slug = _unique("openai-cred")
        p_resp = await client.post(
            "/api/v1/providers",
            headers=headers,
            json={"slug": prov_slug, "name": "OpenAI", "provider_type": ProviderType.CLOUD.value},
        )
        assert p_resp.status_code == 201, p_resp.text
        prov_id = p_resp.json()["id"]

        # 2. Add Credential (BYOK)
        c_resp = await client.post(
            "/api/v1/credentials",
            headers=headers,
            json={
                "provider_id": prov_id,
                "raw_secret": "sk-test-secret-key-12345678",
                "label": "My Test Key",
            },
        )
        assert c_resp.status_code == 201, c_resp.text
        cred_data = c_resp.json()
        cred_id = cred_data["id"]
        
        # Verify NO secret key in output DTO
        assert "raw_secret" not in cred_data
        assert "sk-test-secret" not in str(cred_data)

        # 3. List Credentials
        list_resp = await client.get("/api/v1/credentials", headers=headers)
        assert list_resp.status_code == 200
        assert list_resp.json()["total"] >= 1

        # 4. Revoke
        del_resp = await client.delete(f"/api/v1/credentials/{cred_id}", headers=headers)
        assert del_resp.status_code == 204

        # Verify revoked credential is no longer in active list
        list_resp2 = await client.get("/api/v1/credentials", headers=headers)
        assert list_resp2.status_code == 200
        active_ids = [c["id"] for c in list_resp2.json()["credentials"]]
        assert cred_id not in active_ids