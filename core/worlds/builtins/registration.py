"""
Built-in World & Environment Registration.

Registers the Research World v1 and its supporting environment
in the DSRT registries during startup or on-demand.
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


async def register_builtin_worlds(session: AsyncSession) -> dict[str, str]:
    """Register built-in worlds and their supporting environments (idempotent).

    Returns a mapping of {slug: outcome}.
    """
    results: dict[str, str] = {}

    # 1. Register the Research Workspace environment
    env_repo = EnvironmentRepository(session)
    env_registry = EnvironmentRegistry(env_repo)

    env_slug = RESEARCH_WORKSPACE_MANIFEST.identity.slug
    env_version = RESEARCH_WORKSPACE_MANIFEST.identity.version

    existing_env = await env_repo.get_by_slug(env_slug)
    if existing_env:
        existing_ver = await env_repo.get_version(existing_env.id, env_version)
        if existing_ver:
            results[env_slug] = "already_present"
        else:
            await env_registry.register_environment(
                manifest=RESEARCH_WORKSPACE_MANIFEST,
                implementation_class="core.environments.runtime.workspace_runtime:WorkspaceEnvironmentRuntime",
            )
            results[env_slug] = "registered"
    else:
        await env_registry.register_environment(
            manifest=RESEARCH_WORKSPACE_MANIFEST,
            implementation_class="core.environments.runtime.workspace_runtime:WorkspaceEnvironmentRuntime",
        )
        results[env_slug] = "registered"
        logger.info("builtin_environment_registered", slug=env_slug)

    # 2. Register the Research World
    world_repo = WorldRepository(session)
    world_registry = WorldRegistry(world_repo)

    world_slug = RESEARCH_WORLD_MANIFEST.identity.slug
    world_version = RESEARCH_WORLD_MANIFEST.identity.version

    existing_world = await world_repo.get_by_slug(world_slug)
    if existing_world:
        existing_wv = await world_repo.get_version(existing_world.id, world_version)
        if existing_wv:
            results[world_slug] = "already_present"
        else:
            await world_registry.register_world(
                manifest=RESEARCH_WORLD_MANIFEST,
                implementation_class="core.worlds.builtins.research_world:RESEARCH_WORLD_MANIFEST",
            )
            results[world_slug] = "registered"
    else:
        await world_registry.register_world(
            manifest=RESEARCH_WORLD_MANIFEST,
            implementation_class="core.worlds.builtins.research_world:RESEARCH_WORLD_MANIFEST",
        )
        results[world_slug] = "registered"
        logger.info("builtin_world_registered", slug=world_slug)

    return results