"""Agent Repository — data access for agents, versions, and capabilities."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.repositories.base import Repository
from core.storage.models import Agent, AgentCapability, AgentVersion


class AgentRepository(Repository):
    async def get_by_id(self, agent_id: str) -> Agent | None:
        result = await self._session.execute(
            select(Agent)
            .options(selectinload(Agent.versions))
            .where(Agent.id == agent_id),
        )
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Agent | None:
        result = await self._session.execute(
            select(Agent)
            .options(selectinload(Agent.versions))
            .where(Agent.slug == slug),
        )
        return result.scalar_one_or_none()

    async def list_agents(self, category: str | None = None) -> list[Agent]:
        stmt = select(Agent).options(selectinload(Agent.versions))
        if category:
            stmt = stmt.where(Agent.category == category)
        result = await self._session.execute(stmt.order_by(Agent.slug))
        return list(result.scalars().all())

    async def get_version_by_id(self, version_id: str) -> AgentVersion | None:
        result = await self._session.execute(
            select(AgentVersion)
            .options(selectinload(AgentVersion.agent))
            .where(AgentVersion.id == version_id),
        )
        return result.scalar_one_or_none()

    async def get_version(self, agent_id: str, version: str) -> AgentVersion | None:
        result = await self._session.execute(
            select(AgentVersion).where(
                AgentVersion.agent_id == agent_id,
                AgentVersion.version == version,
            ),
        )
        return result.scalar_one_or_none()

    async def create_agent(
        self,
        *,
        slug: str,
        name: str,
        description: str,
        category: str,
        publisher: str,
        status: str = "REGISTERED",
    ) -> Agent:
        agent = Agent(
            slug=slug,
            name=name,
            description=description,
            category=category,
            publisher=publisher,
            status=status,
        )
        self._session.add(agent)
        await self._session.flush()
        return agent

    async def create_agent_version(
        self,
        *,
        agent_id: str,
        version: str,
        contract_version: str,
        manifest: dict,
        package_reference: str,
        configuration: dict,
        requirements: dict,
        permissions: dict,
        status: str = "ACTIVE",
    ) -> AgentVersion:
        agent_ver = AgentVersion(
            agent_id=agent_id,
            version=version,
            contract_version=contract_version,
            manifest=manifest,
            package_reference=package_reference,
            configuration=configuration,
            requirements=requirements,
            permissions=permissions,
            status=status,
        )
        self._session.add(agent_ver)
        await self._session.flush()
        return agent_ver

    async def link_capability(
        self, agent_version_id: str, capability_id: str,
    ) -> AgentCapability:
        link = AgentCapability(
            agent_version_id=agent_version_id,
            capability_id=capability_id,
        )
        self._session.add(link)
        await self._session.flush()
        return link

    async def find_agents_by_capability(self, capability_slug: str) -> list[AgentVersion]:
        """Find all ACTIVE agent versions supporting a required capability slug."""
        stmt = (
            select(AgentVersion)
            .join(AgentCapability)
            .join(AgentCapability.capability)
            .where(
                AgentVersion.status == "ACTIVE",
                AgentCapability.capability.has(slug=capability_slug),
            )
            .options(selectinload(AgentVersion.agent))
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())