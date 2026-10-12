"""API schemas for /agents endpoints."""

from __future__ import annotations

from schemas.domain import Agent, AgentVersion
from schemas.domain.base import DSRTSchema


class AgentListResponse(DSRTSchema):
    agents: list[Agent]
    total: int


class AgentDetailResponse(DSRTSchema):
    agent: Agent
    latest_version: AgentVersion | None