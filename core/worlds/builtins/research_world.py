"""
Research World v1 — The first concrete DSRT World (C3 §40).

Composes web search, web retrieve, HTTP, filesystem, and Python tools
with research-appropriate policies into a coherent environment for
the Research Intelligence Agent.
"""

from __future__ import annotations

from schemas.domain.world import WorldIdentity, WorldManifest, WorldPolicy
from schemas.domain.enums import FilesystemAccessMode, NetworkMode


RESEARCH_WORLD_MANIFEST = WorldManifest(
    identity=WorldIdentity(
        slug="research_world",
        name="Research World",
        version="1.0.0",
        publisher="dsrt",
    ),
    description=(
        "A composed environment for research agents. Provides web search, "
        "web retrieval, HTTP requests, filesystem workspace, and Python "
        "execution with research-appropriate security policies."
    ),
    required_environments=["research_workspace"],
    exposed_tools=[
        "web.search",
        "web.retrieve",
        "http.request",
        "filesystem.read",
        "filesystem.write",
        "filesystem.list",
        "filesystem.stat",
        "filesystem.delete",
        "filesystem.move",
        "filesystem.promote_to_artifact",
        "python.execute",
    ],
    policy=WorldPolicy(
        network_mode=NetworkMode.CONTROLLED,
        filesystem_access=FilesystemAccessMode.WORKSPACE,
        allow_external_actions=False,
        require_approval_for_external=True,
    ),
    capabilities=["research", "web_research", "data_analysis"],
    reset_supported=True,
    snapshot_supported=False,
)