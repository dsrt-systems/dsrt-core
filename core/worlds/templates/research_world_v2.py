"""
Research World v2 (C7 §29).

Upgraded from the C3 Research World with full C7 component specs,
resource limits, and snapshot support.

Components: Browser, Search, PDF viewer, Document store,
Dataset store, Python, Filesystem, citation/evidence capture.
"""

from __future__ import annotations

from schemas.domain.enums import (
    FilesystemAccessMode,
    NetworkMode,
    WorldClockMode,
    WorldComponentType,
)
from schemas.domain.world import (
    WorldComponentSpec,
    WorldIdentity,
    WorldManifest,
    WorldPolicy,
    WorldResourceLimits,
)


RESEARCH_WORLD_V2_MANIFEST = WorldManifest(
    identity=WorldIdentity(
        slug="research_world",
        name="Research World",
        version="2.0.0",
        publisher="dsrt",
    ),
    description=(
        "Comprehensive research environment with web search, browser, "
        "PDF processing, document storage, Python analysis, and "
        "citation/evidence capture. Supports deep research workflows "
        "with full provenance tracking."
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
        allowed_domains=[
            "scholar.google.com",
            "arxiv.org",
            "pubmed.ncbi.nlm.nih.gov",
            "en.wikipedia.org",
            "www.reuters.com",
            "www.bloomberg.com",
            "www.statista.com",
            "data.worldbank.org",
        ],
        blocked_domains=[],
        filesystem_access=FilesystemAccessMode.WORKSPACE,
        allow_external_actions=False,
        require_approval_for_external=True,
    ),
    capabilities=[
        "research",
        "web_research",
        "data_analysis",
        "evidence_synthesis",
        "citation_generation",
        "report_generation",
        "fact_checking",
        "contradiction_detection",
    ],
    components=[
        WorldComponentSpec(
            component_type=WorldComponentType.FILESYSTEM,
            slug="workspace",
            configuration={
                "subdirs": ["sources", "evidence", "drafts", "output", "data"],
            },
        ),
        WorldComponentSpec(
            component_type=WorldComponentType.BROWSER,
            slug="chromium",
            configuration={"headless": True, "max_tabs": 5},
        ),
        WorldComponentSpec(
            component_type=WorldComponentType.RUNTIME,
            slug="python",
            configuration={
                "version": "3.13",
                "packages": ["pandas", "numpy", "requests", "beautifulsoup4"],
            },
        ),
    ],
    services=[],
    resources=WorldResourceLimits(
        cpu_limit=2,
        memory_mb=4096,
        storage_gb=10,
        max_processes=30,
        max_network_requests=1000,
        max_browser_sessions=5,
        max_duration_seconds=1800,
    ),
    clock_mode=WorldClockMode.REAL_TIME,
    reset_supported=True,
    snapshot_supported=True,
)