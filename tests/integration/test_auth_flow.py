"""
End-to-end auth flow tests.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


def _unique(suffix: str) -> str:
    return f"{suffix}-{uuid.uuid4().hex[:10]}"


class TestAuthEndToEnd:
    async def test_register_creates_user_org_and_token(self, client: AsyncClient):
        email = f"{_unique('alice')}@example.com"
        slug = _unique("acme")

        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "display_name": "Alice",
                "password": "correct-horse-battery",
                "organization_name": "Acme Test",
                "organization_slug": slug,
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["user"]["email"] == email
        assert body["organization"]["slug"] == slug
        assert body["token"]["token_type"] == "bearer"
        assert len(body["token"]["access_token"]) > 20

    async def test_duplicate_email_rejected(self, client: AsyncClient):
        email = f"{_unique('dup')}@example.com"
        slug1 = _unique("orgone")
        slug2 = _unique("orgtwo")

        r1 = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "display_name": "Dup",
                "password": "correct-horse-battery",
                "organization_name": "Org One",
                "organization_slug": slug1,
            },
        )
        assert r1.status_code == 201

        r2 = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "display_name": "Dup",
                "password": "correct-horse-battery",
                "organization_name": "Org Two",
                "organization_slug": slug2,
            },
        )
        assert r2.status_code == 409
        assert r2.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_duplicate_slug_rejected(self, client: AsyncClient):
        slug = _unique("shared")

        r1 = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"{_unique('u1')}@example.com",
                "display_name": "U1",
                "password": "correct-horse-battery",
                "organization_name": "Org",
                "organization_slug": slug,
            },
        )
        assert r1.status_code == 201

        r2 = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"{_unique('u2')}@example.com",
                "display_name": "U2",
                "password": "correct-horse-battery",
                "organization_name": "Org",
                "organization_slug": slug,
            },
        )
        assert r2.status_code == 409

    async def test_login_success_returns_token(self, client: AsyncClient):
        email = f"{_unique('login')}@example.com"

        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "display_name": "L",
                "password": "correct-horse-battery",
                "organization_name": "Org",
                "organization_slug": _unique("loginorg"),
            },
        )
        assert reg.status_code == 201

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "correct-horse-battery"},
        )
        assert login.status_code == 200
        assert "access_token" in login.json()["token"]

    async def test_login_wrong_password_rejected(self, client: AsyncClient):
        email = f"{_unique('wrongpw')}@example.com"

        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "display_name": "L",
                "password": "correct-horse-battery",
                "organization_name": "Org",
                "organization_slug": _unique("wrongpworg"),
            },
        )
        assert reg.status_code == 201

        r = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "WRONG"},
        )
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "AUTHENTICATION_FAILED"

    async def test_login_unknown_email_rejected_same_error(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/auth/login",
            json={
                "email": f"{_unique('ghost')}@example.com",
                "password": "whatever",
            },
        )
        assert r.status_code == 401
        assert r.json()["error"]["message"] == "Invalid email or password."

    async def test_me_requires_bearer_token(self, client: AsyncClient):
        r = await client.get("/api/v1/auth/me")
        assert r.status_code == 401

    async def test_me_returns_identity_and_memberships(self, client: AsyncClient):
        email = f"{_unique('me')}@example.com"
        slug = _unique("meorg")

        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "display_name": "Me User",
                "password": "correct-horse-battery",
                "organization_name": "Me Org",
                "organization_slug": slug,
            },
        )
        assert reg.status_code == 201
        token = reg.json()["token"]["access_token"]
        org_id = reg.json()["organization"]["id"]

        me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me.status_code == 200
        body = me.json()
        assert body["user"]["email"] == email
        assert len(body["memberships"]) == 1
        assert body["memberships"][0]["organization_id"] == org_id
        assert body["memberships"][0]["role"] == "owner"
        assert body["active_organization_id"] == org_id

    async def test_me_with_invalid_token_rejected(self, client: AsyncClient):
        r = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer garbage.token.here"},
        )
        assert r.status_code == 401

    async def test_me_organization_header_must_match_membership(
        self, client: AsyncClient,
    ):
        email = f"{_unique('hdr')}@example.com"

        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "display_name": "H",
                "password": "correct-horse-battery",
                "organization_name": "H",
                "organization_slug": _unique("hdrorg"),
            },
        )
        assert reg.status_code == 201
        token = reg.json()["token"]["access_token"]

        r = await client.get(
            "/api/v1/auth/me",
            headers={
                "Authorization": f"Bearer {token}",
                "X-DSRT-Organization": "org_notarealone",
            },
        )
        assert r.status_code == 403