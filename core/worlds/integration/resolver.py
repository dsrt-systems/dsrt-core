"""
World Resolver (C7 §35, §64-65).

Bridges the C5 Orchestrator to the C7 World Runtime. The orchestrator
calls the resolver to:
  1. Select an appropriate world for a node based on capabilities
  2. Provision a world instance for an execution
  3. Verify the world is ready before agent entry (C7 §37)
  4. Support multi-world execution (C7 §65)

Architecture (C7 §64):
    Node
      ↓
    World Resolver
      ↓
    World Instance
      ↓
    Agent → Tools → World
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.world import WorldManifest

from core.api.errors.exceptions import NotFoundError
from core.observability.logging import get_logger
from core.repositories.world_repository import WorldRepository
from core.worlds.components.manager import ComponentManager
from core.worlds.components.component import ComponentContext
from core.worlds.manager.manager import WorldManager
from core.worlds.registry.registry import WorldRegistry


logger = get_logger("dsrt.worlds.resolver")


@dataclass
class WorldSelection:
    """Result of selecting a world for a node."""
    world_slug: str
    world_version: str
    world_version_id: str
    capabilities: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class WorldProvisionResult:
    """Result of provisioning a world instance."""
    instance_id: str
    world_slug: str
    status: str
    components_ready: list[str] = field(default_factory=list)
    components_failed: list[str] = field(default_factory=list)
    is_agent_ready: bool = False
    reason: str = ""


class WorldResolver:
    """Resolves and provisions worlds for C5 orchestration nodes (C7 §35, §64).

    Usage (called by C5 Orchestrator):
        resolver = WorldResolver(session)

        # Step 1: Select a world for a node
        selection = await resolver.select_world(
            required_capabilities=["browser", "terminal", "python"],
            organization_id="org_1",
        )

        # Step 2: Provision the world
        result = await resolver.provision_world(
            world_slug=selection.world_slug,
            organization_id="org_1",
            execution_id="exe_1",
            task_id="tsk_1",
        )

        # Step 3: Check if agent can enter
        if result.is_agent_ready:
            # Agent can start working in the world
            pass
    """

    def __init__(
        self,
        session: AsyncSession,
        world_manager: WorldManager | None = None,
    ) -> None:
        self._session = session
        self._world_repo = WorldRepository(session)
        self._world_registry = WorldRegistry(self._world_repo)
        self._world_manager = world_manager or WorldManager(session)

    async def select_world(
        self,
        required_capabilities: list[str],
        organization_id: str,
        preferred_world: str | None = None,
    ) -> WorldSelection | None:
        """Select the best world for a set of required capabilities (C7 §35).

        Selection criteria:
          1. If preferred_world is specified and matches, use it
          2. Otherwise, find worlds whose capabilities are a superset
          3. Prefer worlds with fewer excess capabilities (best fit)

        Args:
            required_capabilities: Capabilities the node needs.
            organization_id: For future policy filtering.
            preferred_world: Explicit world slug preference.

        Returns:
            WorldSelection or None if no matching world found.
        """
        # Load all registered worlds
        worlds = await self._world_registry.list_worlds()

        if not worlds:
            logger.warning("no_worlds_registered")
            return None

        # Check preferred world first
        if preferred_world:
            for w in worlds:
                if w.slug == preferred_world:
                    try:
                        ver = await self._world_registry.resolve_world_version(w.slug)
                        manifest = ver.manifest
                        caps = set(manifest.get("capabilities", []))
                        if set(required_capabilities).issubset(caps):
                            return WorldSelection(
                                world_slug=w.slug,
                                world_version=ver.version,
                                world_version_id=ver.id,
                                capabilities=list(caps),
                                components=[
                                    c.get("slug", "")
                                    for c in manifest.get("components", [])
                                ],
                                reason="Preferred world matches requirements.",
                            )
                    except NotFoundError:
                        pass

        # Find all eligible worlds
        candidates: list[tuple[str, str, str, set[str], int]] = []
        for w in worlds:
            try:
                ver = await self._world_registry.resolve_world_version(w.slug)
                manifest = ver.manifest
                caps = set(manifest.get("capabilities", []))

                if set(required_capabilities).issubset(caps):
                    excess = len(caps) - len(set(required_capabilities))
                    candidates.append((w.slug, ver.version, ver.id, caps, excess))
            except NotFoundError:
                continue

        if not candidates:
            logger.warning(
                "no_matching_world",
                required=required_capabilities,
            )
            return None

        # Sort by best fit (fewest excess capabilities)
        candidates.sort(key=lambda c: c[4])
        best = candidates[0]

        return WorldSelection(
            world_slug=best[0],
            world_version=best[1],
            world_version_id=best[2],
            capabilities=list(best[3]),
            reason=f"Best fit: {best[4]} excess capabilities.",
        )

    async def provision_world(
        self,
        world_slug: str,
        organization_id: str,
        execution_id: str | None = None,
        task_id: str | None = None,
        world_version: str | None = None,
        policy_overrides: dict[str, Any] | None = None,
    ) -> WorldProvisionResult:
        """Provision a world instance for an execution (C7 §36).

        Pipeline (C7 §36):
          1. Resolve world definition
          2. Provision instance
          3. Apply snapshot (if base exists)
          4. Apply policies
          5. Inject permitted credentials
          6. Health check
          7. AGENT READY

        Returns:
            WorldProvisionResult with instance ID and readiness status.
        """
        try:
            # 1-5. Delegate to WorldManager.provision()
            instance = await self._world_manager.provision(
                world_slug=world_slug,
                world_version=world_version,
                organization_id=organization_id,
                task_id=task_id,
                execution_id=execution_id,
                policy_overrides=policy_overrides,
            )

            # 6. Start the world
            instance = await self._world_manager.start(instance.id)

            # 7. Health check
            health = await self._world_manager.health(instance.id)
            is_ready = health.status.value in ("RUNNING", "ACTIVE", "READY")

            logger.info(
                "world_provisioned_for_execution",
                instance_id=instance.id,
                world_slug=world_slug,
                execution_id=execution_id,
                is_ready=is_ready,
            )

            return WorldProvisionResult(
                instance_id=instance.id,
                world_slug=world_slug,
                status=instance.status,
                is_agent_ready=is_ready,
                reason="World provisioned and healthy." if is_ready else "World provisioned but health check degraded.",
            )

        except Exception as e:
            logger.error(
                "world_provision_failed",
                world_slug=world_slug,
                execution_id=execution_id,
                error=str(e),
            )
            return WorldProvisionResult(
                instance_id="",
                world_slug=world_slug,
                status="FAILED",
                is_agent_ready=False,
                reason=f"Provisioning failed: {str(e)[:200]}",
            )

    async def check_agent_readiness(
        self,
        instance_id: str,
    ) -> tuple[bool, list[str]]:
        """Check if a world is ready for agent entry (C7 §37).

        Startup contract:
          - filesystem healthy
          - browser healthy (if present)
          - database healthy (if present)
          - network policy loaded
          - credentials available
          - resource limits active
          - telemetry active

        Returns:
            (is_ready, list_of_unready_components)
        """
        try:
            health = await self._world_manager.health(instance_id)

            unready: list[str] = []
            for comp_name, comp_status in health.components.items():
                if comp_status not in ("healthy", "READY"):
                    unready.append(comp_name)

            is_ready = len(unready) == 0 and health.status.value in (
                "RUNNING", "ACTIVE", "READY",
            )

            return is_ready, unready

        except Exception as e:
            logger.error(
                "agent_readiness_check_failed",
                instance_id=instance_id,
                error=str(e),
            )
            return False, [f"health_check_error: {str(e)[:100]}"]

    async def release_world(
        self,
        instance_id: str,
    ) -> bool:
        """Release a world instance after execution completes (C7 §55).

        Takes a final snapshot, then destroys the instance.
        """
        try:
            # Take final snapshot before destruction
            await self._world_manager.snapshot(
                instance_id, snapshot_type="checkpoint",
            )

            # Destroy
            return await self._world_manager.destroy(instance_id)

        except Exception as e:
            logger.error(
                "world_release_failed",
                instance_id=instance_id,
                error=str(e),
            )
            return False