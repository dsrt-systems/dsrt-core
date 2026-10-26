"""
Built-in World & Environment Registration (C3 + C7).

Registers all built-in worlds and their supporting environments.
C3: Research World v1
C7: Software Engineering World v1, Data Science World v1, Research World v2
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.environment import (
    EnvironmentIdentity,
    EnvironmentManifest,
)
from schemas.domain.enums import EnvironmentType

from core.environments.registry.registry import EnvironmentRegistry
from core.observability.logging import get_logger
from core.repositories.environment_repository import EnvironmentRepository
from core.repositories.world_repository import WorldRepository
from core.worlds.builtins.research_world import RESEARCH_WORLD_MANIFEST
from core.worlds.registry.registry import WorldRegistry
from core.worlds.templates import (
    DATA_SCIENCE_WORLD_MANIFEST,
    RESEARCH_WORLD_V2_MANIFEST,
    SOFTWARE_WORLD_MANIFEST,
)


logger = get_logger("dsrt.worlds.builtins.registration")


RESEARCH_WORKSPACE_MANIFEST = EnvironmentManifest(
    identity=EnvironmentIdentity(
        slug="research_workspace",
        name="Research Workspace",
        version="1.0.0",
        environment_type=EnvironmentType.FILE,
    ),
    description=(
        "Isolated filesystem workspace for research agents. "
        "Provides input/, working/, output/, and temp/ directories."
    ),
    installed_tools=[
        "filesystem.read",
        "filesystem.write",
        "filesystem.list",
        "filesystem.stat",
        "filesystem.delete",
        "filesystem.move",
        "filesystem.promote_to_artifact",
        "python.execute",
    ],
)

SOFTWARE_WORKSPACE_MANIFEST = EnvironmentManifest(
    identity=EnvironmentIdentity(
        slug="software_workspace",
        name="Software Workspace",
        version="1.0.0",
        environment_type=EnvironmentType.FILE,
    ),
    description=(
        "Isolated filesystem workspace for software engineering agents. "
        "Provides src/, tests/, docs/, config/, and data/ directories."
    ),
    installed_tools=[
        "filesystem.read",
        "filesystem.write",
        "filesystem.list",
        "filesystem.stat",
        "filesystem.delete",
        "filesystem.move",
        "filesystem.promote_to_artifact",
        "python.execute",
    ],
)

DATA_SCIENCE_WORKSPACE_MANIFEST = EnvironmentManifest(
    identity=EnvironmentIdentity(
        slug="data_science_workspace",
        name="Data Science Workspace",
        version="1.0.0",
        environment_type=EnvironmentType.FILE,
    ),
    description=(
        "Isolated filesystem workspace for data science agents. "
        "Provides data/, notebooks/, output/, scripts/, and models/ directories."
    ),
    installed_tools=[
        "filesystem.read",
        "filesystem.write",
        "filesystem.list",
        "filesystem.stat",
        "filesystem.promote_to_artifact",
        "python.execute",
    ],
)


async def _ensure_environment(
    env_repo: EnvironmentRepository,
    env_registry: EnvironmentRegistry,
    manifest: EnvironmentManifest,
    impl_class: str,
    results: dict[str, str],
) -> None:
    """Register an environment if not already present."""
    slug = manifest.identity.slug
    version = manifest.identity.version

    existing = await env_repo.get_by_slug(slug)
    if existing:
        existing_ver = await env_repo.get_version(existing.id, version)
        if existing_ver:
            results[slug] = "already_present"
            return

    await env_registry.register_environment(
        manifest=manifest,
        implementation_class=impl_class,
    )
    results[slug] = "registered"
    logger.info("builtin_environment_registered", slug=slug)


async def _ensure_world(
    world_repo: WorldRepository,
    world_registry: WorldRegistry,
    manifest,
    impl_class: str,
    results: dict[str, str],
) -> None:
    """Register a world if not already present."""
    slug = manifest.identity.slug
    version = manifest.identity.version

    existing = await world_repo.get_by_slug(slug)
    if existing:
        existing_wv = await world_repo.get_version(existing.id, version)
        if existing_wv:
            results[slug] = "already_present"
            return

    await world_registry.register_world(
        manifest=manifest,
        implementation_class=impl_class,
    )
    results[slug] = "registered"
    logger.info("builtin_world_registered", slug=slug)


async def register_builtin_worlds(session: AsyncSession) -> dict[str, str]:
    """Register all built-in worlds and environments (idempotent).

    Returns a mapping of {slug: outcome}.
    """
    results: dict[str, str] = {}

    env_repo = EnvironmentRepository(session)
    env_registry = EnvironmentRegistry(env_repo)
    world_repo = WorldRepository(session)
    world_registry = WorldRegistry(world_repo)

    ws_impl = "core.environments.runtime.workspace_runtime:WorkspaceEnvironmentRuntime"

    # --- Environments ---
    await _ensure_environment(
        env_repo, env_registry,
        RESEARCH_WORKSPACE_MANIFEST, ws_impl, results,
    )
    await _ensure_environment(
        env_repo, env_registry,
        SOFTWARE_WORKSPACE_MANIFEST, ws_impl, results,
    )
    await _ensure_environment(
        env_repo, env_registry,
        DATA_SCIENCE_WORKSPACE_MANIFEST, ws_impl, results,
    )

    # --- Worlds ---
    # C3 Research World v1 (preserved for backward compatibility)
    await _ensure_world(
        world_repo, world_registry,
        RESEARCH_WORLD_MANIFEST,
        "core.worlds.builtins.research_world:RESEARCH_WORLD_MANIFEST",
        results,
    )

    # C7 Research World v2 (upgraded)
    await _ensure_world(
        world_repo, world_registry,
        RESEARCH_WORLD_V2_MANIFEST,
        "core.worlds.templates.research_world_v2:RESEARCH_WORLD_V2_MANIFEST",
        results,
    )

    # C7 Software Engineering World
    await _ensure_world(
        world_repo, world_registry,
        SOFTWARE_WORLD_MANIFEST,
        "core.worlds.templates.software_world:SOFTWARE_WORLD_MANIFEST",
        results,
    )

    # C7 Data Science World
    await _ensure_world(
        world_repo, world_registry,
        DATA_SCIENCE_WORLD_MANIFEST,
        "core.worlds.templates.data_science_world:DATA_SCIENCE_WORLD_MANIFEST",
        results,
    )

    return results