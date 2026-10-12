"""Unit tests for ToolRegistry and ToolRepository."""

from __future__ import annotations

import uuid
import pytest

from core.storage.database import db_manager
from core.tools.registry.registry import ToolRegistry
from core.tools.errors import ToolNotFoundError
from schemas.domain.enums import (
    SideEffectClass,
    ToolRiskLevel,
    ToolStatus,
)
from schemas.domain.tool import (
    ToolCapabilityDeclaration,
    ToolIdentity,
    ToolLimits,
    ToolManifest,
    ToolRetryPolicy,
)


def _sample_manifest(
    slug: str = "web.search",
    version: str = "1.0.0",
    capabilities: list[str] | None = None,
) -> ToolManifest:
    caps = capabilities or ["web.search", "information.retrieval"]
    return ToolManifest(
        identity=ToolIdentity(
            slug=slug,
            name="Web Search",
            version=version,
            category="web",
        ),
        description="Search the web for current data.",
        capabilities=[ToolCapabilityDeclaration(slug=c) for c in caps],
        risk_level=ToolRiskLevel.LOW,
        side_effect=SideEffectClass.READ,
        limits=ToolLimits(timeout_seconds=30),
        retry=ToolRetryPolicy(allowed=True, max_attempts=3, idempotent=True),
    )


@pytest.mark.asyncio
async def test_register_tool_and_resolve() -> None:
    from core.repositories.tool_repository import ToolRepository

    unique_slug = f"test.search.{uuid.uuid4().hex[:8]}"

    async with db_manager.session() as session:
        repo = ToolRepository(session)
        registry = ToolRegistry(repo)

        manifest = _sample_manifest(unique_slug, "1.0.0")
        version_res = await registry.register_tool(
            manifest=manifest,
            implementation_class="core.tools.builtins.web_search:WebSearchTool",
        )

        assert version_res.version == "1.0.0"
        assert version_res.manifest.identity.slug == unique_slug
        assert version_res.status == ToolStatus.ACTIVE

        # Fetch tool
        tool = await registry.get_tool(unique_slug)
        assert tool.slug == unique_slug
        assert tool.latest_version == "1.0.0"

        # Resolve latest version
        resolved = await registry.resolve_tool_version(unique_slug)
        assert resolved.id == version_res.id
        assert resolved.version == "1.0.0"


@pytest.mark.asyncio
async def test_resolve_tool_not_found() -> None:
    from core.repositories.tool_repository import ToolRepository

    async with db_manager.session() as session:
        repo = ToolRepository(session)
        registry = ToolRegistry(repo)

        with pytest.raises(ToolNotFoundError):
            await registry.get_tool(f"non.existent.{uuid.uuid4().hex[:8]}")

        with pytest.raises(ToolNotFoundError):
            await registry.resolve_tool_version(f"non.existent.{uuid.uuid4().hex[:8]}")


@pytest.mark.asyncio
async def test_capability_discovery() -> None:
    from core.repositories.tool_repository import ToolRepository

    cap_a = f"cap.a.{uuid.uuid4().hex[:8]}"
    cap_b = f"cap.b.{uuid.uuid4().hex[:8]}"
    slug1 = f"tool.a.{uuid.uuid4().hex[:8]}"
    slug2 = f"tool.b.{uuid.uuid4().hex[:8]}"

    async with db_manager.session() as session:
        repo = ToolRepository(session)
        registry = ToolRegistry(repo)

        m1 = _sample_manifest(slug1, "1.0.0", [cap_a, cap_b])
        m2 = _sample_manifest(slug2, "1.0.0", [cap_b])

        await registry.register_tool(manifest=m1, implementation_class="impl.A")
        await registry.register_tool(manifest=m2, implementation_class="impl.B")

        discovery = await registry.discover_tools_for_capabilities([cap_a, cap_b])
        assert len(discovery[cap_a]) == 1
        assert len(discovery[cap_b]) == 2
        assert discovery[cap_a][0].manifest.identity.slug == slug1