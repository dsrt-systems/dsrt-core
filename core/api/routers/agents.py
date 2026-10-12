"""
/api/v1/agents endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from core.agents.registry import AgentRegistry
from core.api.dependencies import (
    get_security_context,
    get_session,
)
from core.repositories import AgentRepository, CapabilityRepository
from core.security.context import SecurityContext
from schemas.api.agents import AgentDetailResponse, AgentListResponse
from schemas.domain import Agent, AgentRegistrationRequest, AgentVersion


router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


def get_agent_registry(session=Depends(get_session)) -> AgentRegistry:
    return AgentRegistry(
        agent_repo=AgentRepository(session),
        capability_repo=CapabilityRepository(session),
    )


@router.get("", response_model=AgentListResponse, summary="List registered agents.")
async def list_agents(
    category: str | None = None,
    registry: AgentRegistry = Depends(get_agent_registry),
    context: SecurityContext = Depends(get_security_context),
) -> AgentListResponse:
    agents = await registry.list_agents(category=category)
    return AgentListResponse(agents=agents, total=len(agents))


@router.get("/{slug}", response_model=AgentDetailResponse, summary="Get agent details.")
async def get_agent(
    slug: str,
    registry: AgentRegistry = Depends(get_agent_registry),
    context: SecurityContext = Depends(get_security_context),
) -> AgentDetailResponse:
    agent = await registry.get_agent(slug)
    try:
        latest = await registry.resolve_agent_version(slug)
    except Exception:
        latest = None
    return AgentDetailResponse(agent=agent, latest_version=latest)


@router.get("/{slug}/versions/{version}", response_model=AgentVersion, summary="Get agent version.")
async def get_agent_version(
    slug: str,
    version: str,
    registry: AgentRegistry = Depends(get_agent_registry),
    context: SecurityContext = Depends(get_security_context),
) -> AgentVersion:
    return await registry.get_agent_version(slug, version)


@router.post(
    "/register",
    response_model=AgentVersion,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new agent version package.",
)
async def register_agent(
    body: AgentRegistrationRequest,
    registry: AgentRegistry = Depends(get_agent_registry),
    context: SecurityContext = Depends(get_security_context),
) -> AgentVersion:
    return await registry.register_agent(body)