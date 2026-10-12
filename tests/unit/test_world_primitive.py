"""Unit tests for the World Primitive (C3 §39-40)."""

from __future__ import annotations

import uuid
import pytest

from schemas.domain.world import WorldIdentity, WorldManifest, WorldPolicy
from schemas.domain.enums import NetworkMode

from core.repositories.world_repository import WorldRepository
from core.storage.database import db_manager
from core.worlds.builtins.research_world import RESEARCH_WORLD_MANIFEST
from core.worlds.registry.registry import WorldRegistry


class TestResearchWorldManifest:
    def test_identity(self):
        assert RESEARCH_WORLD_MANIFEST.identity.slug == "research_world"
        assert RESEARCH_WORLD_MANIFEST.identity.version == "1.0.0"

    def test_exposes_research_tools(self):
        tools = RESEARCH_WORLD_MANIFEST.exposed_tools
        assert "web.search" in tools
        assert "web.retrieve" in tools
        assert "python.execute" in tools
        assert "filesystem.read" in tools

    def test_policy_is_controlled(self):
        assert RESEARCH_WORLD_MANIFEST.policy.network_mode == NetworkMode.CONTROLLED
        assert RESEARCH_WORLD_MANIFEST.policy.allow_external_actions is False
        assert RESEARCH_WORLD_MANIFEST.policy.require_approval_for_external is True

    def test_declares_capabilities(self):
        assert "research" in RESEARCH_WORLD_MANIFEST.capabilities


class TestWorldRegistry:
    @pytest.mark.asyncio
    async def test_register_and_resolve(self):
        suffix = uuid.uuid4().hex[:8]

        async with db_manager.session() as session:
            repo = WorldRepository(session)
            registry = WorldRegistry(repo)

            manifest = WorldManifest(
                identity=WorldIdentity(
                    slug=f"test_world_{suffix}",
                    name="Test World",
                    version="1.0.0",
                ),
                exposed_tools=["web.search"],
                capabilities=["test"],
            )

            version = await registry.register_world(
                manifest=manifest,
                implementation_class="test.impl:TestWorld",
            )
            assert version.version == "1.0.0"

            resolved = await registry.resolve_world_version(f"test_world_{suffix}")
            assert resolved.id == version.id


class TestWorldRegistration:
    @pytest.mark.asyncio
    async def test_builtin_registration_idempotent(self):
        from core.worlds.builtins.registration import register_builtin_worlds

        async with db_manager.session() as session:
            results_1 = await register_builtin_worlds(session)
            assert "research_world" in results_1

        async with db_manager.session() as session:
            results_2 = await register_builtin_worlds(session)
            assert results_2["research_world"] == "already_present"
            assert results_2["research_workspace"] == "already_present"