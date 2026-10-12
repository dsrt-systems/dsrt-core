"""
Agent Registry Service.

Manages agent lifecycle, version registration, and lookup (C1 §14-15).
"""

from __future__ import annotations

from core.agents.validator import AgentValidator
from core.api.errors.exceptions import ConflictError, NotFoundError
from core.capabilities.registry import CapabilityRegistry
from core.observability.logging import get_logger
from core.repositories import AgentRepository, CapabilityRepository
from core.storage.models import AgentVersion as AgentVersionORM
from schemas.domain import (
    Agent,
    AgentManifest,
    AgentRegistrationRequest,
    AgentVersion,
)


logger = get_logger("dsrt.agents")


class AgentRegistry:
    def __init__(
        self,
        agent_repo: AgentRepository,
        capability_repo: CapabilityRepository,
    ) -> None:
        self._repo = agent_repo
        self._cap_repo = capability_repo
        self._cap_registry = CapabilityRegistry(capability_repo)
        self._validator = AgentValidator(self._cap_registry)

    async def register_agent(
        self, request: AgentRegistrationRequest,
    ) -> AgentVersion:
        """Register a new agent package & version through the validation pipeline."""
        manifest = request.manifest
        agent_id = manifest.identity.id
        version = manifest.identity.version

        # 1. Pipeline validation (schema -> contract -> capabilities)
        await self._validator.validate_manifest(manifest)

        # 2. Check if Agent parent record exists or create it
        agent = await self._repo.get_by_slug(agent_id)
        if not agent:
            agent = await self._repo.create_agent(
                slug=agent_id,
                name=manifest.identity.name,
                description=manifest.description,
                category=manifest.identity.category,
                publisher=manifest.identity.publisher,
                status="ACTIVE",
            )

        # 3. Check for version collision
        existing_version = await self._repo.get_version(agent.id, version)
        if existing_version:
            raise ConflictError(
                f"Agent '{agent_id}' version '{version}' is already registered.",
                metadata={"agent_id": agent_id, "version": version},
            )

        # 4. Create AgentVersion
        ver_orm = await self._repo.create_agent_version(
            agent_id=agent.id,
            version=version,
            contract_version=manifest.identity.contract_version,
            manifest=manifest.model_dump(),
            package_reference=request.package_reference,
            configuration=manifest.configuration,
            requirements=manifest.requirements.model_dump(),
            permissions=manifest.permissions.model_dump(),
            status="ACTIVE",
        )

        # 5. Link declared capabilities
        for cap_slug in manifest.capabilities:
            cap = await self._cap_repo.get_by_slug(cap_slug)
            if cap:
                await self._repo.link_capability(ver_orm.id, cap.id)

        logger.info(
            "agent_registered",
            agent_slug=agent_id,
            version=version,
            version_id=ver_orm.id,
        )

        return self._to_version_schema(ver_orm, manifest)

    async def get_agent(self, slug: str) -> Agent:
        agent = await self._repo.get_by_slug(slug)
        if not agent:
            raise NotFoundError(
                f"Agent '{slug}' not found.", metadata={"slug": slug},
            )
        return Agent.model_validate(agent, from_attributes=True)

    async def get_agent_version(self, slug: str, version: str) -> AgentVersion:
        agent = await self._repo.get_by_slug(slug)
        if not agent:
            raise NotFoundError(f"Agent '{slug}' not found.")
        ver = await self._repo.get_version(agent.id, version)
        if not ver:
            raise NotFoundError(f"Agent '{slug}' version '{version}' not found.")
        manifest = AgentManifest(**ver.manifest)
        return self._to_version_schema(ver, manifest)

    async def resolve_agent_version(
        self, slug: str, requested_version: str | None = None,
    ) -> AgentVersion:
        """Resolve an agent slug + optional version constraint to an active AgentVersion."""
        agent = await self._repo.get_by_slug(slug)
        if not agent or agent.status != "ACTIVE":
            raise NotFoundError(f"Active agent '{slug}' not found.")

        if requested_version:
            ver = await self._repo.get_version(agent.id, requested_version)
            if not ver or ver.status != "ACTIVE":
                raise NotFoundError(
                    f"Active agent version '{slug}@{requested_version}' not found.",
                )
        else:
            # Pick latest active version
            active_versions = [v for v in agent.versions if v.status == "ACTIVE"]
            if not active_versions:
                raise NotFoundError(f"No active versions available for agent '{slug}'.")
            ver = sorted(active_versions, key=lambda x: x.version, reverse=True)[0]

        manifest = AgentManifest(**ver.manifest)
        return self._to_version_schema(ver, manifest)

    async def list_agents(self, category: str | None = None) -> list[Agent]:
        agents = await self._repo.list_agents(category=category)
        return [Agent.model_validate(a, from_attributes=True) for a in agents]

    @staticmethod
    def _to_version_schema(orm: AgentVersionORM, manifest: AgentManifest) -> AgentVersion:
        return AgentVersion(
            id=orm.id,
            agent_id=orm.agent_id,
            version=orm.version,
            contract_version=orm.contract_version,
            manifest=manifest,
            package_reference=orm.package_reference,
            configuration=orm.configuration,
            requirements=manifest.requirements,
            permissions=manifest.permissions,
            status=orm.status,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )