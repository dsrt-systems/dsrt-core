"""
Data Science World v1 (C7 §30).

Components: Python, Jupyter, datasets, pandas, numpy, SQL,
database, filesystem, visualization.

Agent can: inspect data, clean, analyze, visualize, export.
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


DATA_SCIENCE_WORLD_MANIFEST = WorldManifest(
    identity=WorldIdentity(
        slug="data_science_world",
        name="Data Science World",
        version="1.0.0",
        publisher="dsrt",
    ),
    description=(
        "Data science and analysis environment with Python, Jupyter, "
        "pandas, numpy, SQL database, and visualization tools. "
        "Supports data inspection, cleaning, analysis, and reporting."
    ),
    required_environments=["data_science_workspace"],
    exposed_tools=[
        "filesystem.read",
        "filesystem.write",
        "filesystem.list",
        "filesystem.stat",
        "filesystem.promote_to_artifact",
        "python.execute",
        "database.query",
        "http.request",
        "web.search",
        "web.retrieve",
    ],
    policy=WorldPolicy(
        network_mode=NetworkMode.RESTRICTED,
        allowed_domains=[
            "pypi.org",
            "raw.githubusercontent.com",
            "api.github.com",
            "data.world",
            "kaggle.com",
        ],
        blocked_domains=[],
        filesystem_access=FilesystemAccessMode.WORKSPACE,
        allow_external_actions=False,
        require_approval_for_external=True,
    ),
    capabilities=[
        "data_analysis",
        "data_cleaning",
        "statistical_analysis",
        "visualization",
        "sql_query",
        "dataset_inspection",
        "report_generation",
    ],
    components=[
        WorldComponentSpec(
            component_type=WorldComponentType.FILESYSTEM,
            slug="workspace",
            configuration={
                "subdirs": ["data", "notebooks", "output", "scripts", "models"],
            },
        ),
        WorldComponentSpec(
            component_type=WorldComponentType.RUNTIME,
            slug="python",
            configuration={
                "version": "3.13",
                "packages": [
                    "pandas", "numpy", "scipy", "matplotlib",
                    "seaborn", "scikit-learn", "jupyter",
                ],
            },
        ),
        WorldComponentSpec(
            component_type=WorldComponentType.DATABASE,
            slug="postgres",
            configuration={"version": "16", "extensions": ["pgvector"]},
        ),
    ],
    services=["postgres"],
    resources=WorldResourceLimits(
        cpu_limit=4,
        memory_mb=16384,
        storage_gb=50,
        max_processes=50,
        max_network_requests=200,
        max_browser_sessions=0,
        max_duration_seconds=7200,
    ),
    clock_mode=WorldClockMode.REAL_TIME,
    reset_supported=True,
    snapshot_supported=True,
)