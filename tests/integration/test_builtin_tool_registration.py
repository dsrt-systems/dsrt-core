"""Integration test: register built-in tools and verify they're resolvable (C3.7)."""

from __future__ import annotations

import pytest

from core.storage.database import db_manager
from core.tools.builtins.registration import register_builtin_tools
from core.repositories.tool_repository import ToolRepository
from core.tools.registry.registry import ToolRegistry


@pytest.mark.asyncio
async def test_register_builtin_tools_is_idempotent():
    """Register built-in tools twice; second call should report 'already_present'."""
    async with db_manager.session() as session:
        results_1 = await register_builtin_tools(session)
        assert "web.search" in results_1
        assert "web.retrieve" in results_1
        assert "http.request" in results_1

    async with db_manager.session() as session:
        results_2 = await register_builtin_tools(session)
        for slug, outcome in results_2.items():
            assert outcome == "already_present", f"{slug} should be already_present on second run"


@pytest.mark.asyncio
async def test_builtins_discoverable_via_registry():
    """After registration, built-in tools must be resolvable via the Registry."""
    async with db_manager.session() as session:
        await register_builtin_tools(session)

    async with db_manager.session() as session:
        repo = ToolRepository(session)
        registry = ToolRegistry(repo)

        web_search = await registry.resolve_tool_version("web.search")
        assert web_search.manifest.identity.slug == "web.search"
        assert web_search.implementation_class == "core.tools.builtins.web_search:WebSearchTool"

        web_retrieve = await registry.resolve_tool_version("web.retrieve")
        assert web_retrieve.manifest.identity.slug == "web.retrieve"

        http_request = await registry.resolve_tool_version("http.request")
        assert http_request.manifest.identity.slug == "http.request"