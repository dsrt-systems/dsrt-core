"""
Software Engineering World v1 (C7 §28).

Components: Git repository, Terminal, Python, Node.js, Package manager,
Database, Redis, Browser, Test runner, CI simulator, Filesystem.

Agent can: inspect repo, edit files, run tests, start application,
inspect database, use browser, debug, commit changes.
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


SOFTWARE_WORLD_MANIFEST = WorldManifest(
    identity=WorldIdentity(
        slug="software_engineering_world",
        name="Software Engineering World",
        version="1.0.0",
        publisher="dsrt",
    ),
    description=(
        "Full-stack software engineering environment with Git, terminal, "
        "Python, Node.js, database, browser, and test runner. "
        "Supports code inspection, editing, testing, debugging, and deployment."
    ),
    required_environments=["software_workspace"],
    exposed_tools=[
        "filesystem.read",
        "filesystem.write",
        "filesystem.list",
        "filesystem.stat",
        "filesystem.delete",
        "filesystem.move",
        "filesystem.promote_to_artifact",
        "python.execute",
        "shell.execute",
        "http.request",
        "web.search",
        "web.retrieve",
        "database.query",
    ],
    policy=WorldPolicy(
        network_mode=NetworkMode.RESTRICTED,
        allowed_domains=[
            "pypi.org",
            "registry.npmjs.org",
            "github.com",
            "raw.githubusercontent.com",
            "api.github.com",
            "docs.python.org",
            "nodejs.org",
        ],
        blocked_domains=[],
        filesystem_access=FilesystemAccessMode.WORKSPACE,
        allow_external_actions=False,
        require_approval_for_external=True,
    ),
    capabilities=[
        "software_engineering",
        "code_generation",
        "code_review",
        "testing",
        "debugging",
        "git_operations",
        "database_operations",
        "browser_testing",
    ],
    components=[
        WorldComponentSpec(
            component_type=WorldComponentType.FILESYSTEM,
            slug="workspace",
            configuration={"subdirs": ["src", "tests", "docs", "config", "data"]},
        ),
        WorldComponentSpec(
            component_type=WorldComponentType.TERMINAL,
            slug="terminal",
            configuration={"shell": "bash", "timeout_seconds": 120},
        ),
        WorldComponentSpec(
            component_type=WorldComponentType.RUNTIME,
            slug="python",
            configuration={"version": "3.13", "packages": ["pytest", "ruff", "mypy"]},
        ),
        WorldComponentSpec(
            component_type=WorldComponentType.RUNTIME,
            slug="nodejs",
            configuration={"version": "20", "packages": ["jest", "eslint"]},
            required=False,
        ),
        WorldComponentSpec(
            component_type=WorldComponentType.DATABASE,
            slug="postgres",
            configuration={"version": "16", "extensions": ["pgvector"]},
            required=False,
        ),
        WorldComponentSpec(
            component_type=WorldComponentType.BROWSER,
            slug="chromium",
            configuration={"headless": True},
            required=False,
        ),
    ],
    services=["postgres", "redis"],
    resources=WorldResourceLimits(
        cpu_limit=4,
        memory_mb=8192,
        storage_gb=20,
        max_processes=100,
        max_network_requests=500,
        max_browser_sessions=2,
        max_duration_seconds=3600,
    ),
    clock_mode=WorldClockMode.REAL_TIME,
    reset_supported=True,
    snapshot_supported=True,
)