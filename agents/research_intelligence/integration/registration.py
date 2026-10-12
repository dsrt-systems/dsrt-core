"""
Research Intelligence Agent — Registration Integration.

Registers required capabilities in the Capability Registry and then registers the
agent manifest with the Agent Registry. Designed to be called from a bootstrap
script or an integration test using an active Core DB session.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from agents.research_intelligence.runtime.agent import _load_manifest
from core.agents.registry import AgentRegistry
from core.api.errors.exceptions import ConflictError
from core.capabilities.registry import CapabilityRegistry
from core.repositories import AgentRepository, CapabilityRepository
from schemas.domain import AgentRegistrationRequest, CapabilityCreate, RiskLevel


_MANIFEST_PATH = Path(__file__).resolve().parents[1] / "manifest.yaml"


def _capability_seed() -> list[dict[str, Any]]:
    """Every capability declared by the manifest is registered as low-risk stub."""
    with _MANIFEST_PATH.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    caps = set(raw.get("capabilities", []))
    caps.update(raw.get("requirements", {}).get("required_capabilities", []))
    caps.update(raw.get("requirements", {}).get("optional_capabilities", []))
    return [
        {
            "slug": slug,
            "name": slug.replace("_", " ").title(),
            "description": f"Capability registered by research_intelligence agent: {slug}.",
            "version": "1.0.0",
        }
        for slug in sorted(caps)
    ]


async def register_agent(session: AsyncSession) -> dict[str, Any]:
    """Register capabilities and the research_intelligence agent."""
    cap_repo = CapabilityRepository(session)
    agent_repo = AgentRepository(session)
    cap_registry = CapabilityRegistry(cap_repo)
    agent_registry = AgentRegistry(agent_repo, cap_repo)

    # 1. Ensure capabilities exist (idempotent).
    for cap in _capability_seed():
        try:
            await cap_registry.register_capability(
                CapabilityCreate(
                    slug=cap["slug"],
                    name=cap["name"],
                    description=cap["description"],
                    version=cap["version"],
                    risk_level=RiskLevel.LOW,
                )
            )
        except ConflictError:
            pass  # Already registered.

    # 2. Register the agent version (idempotent — surfaces existing on conflict).
    manifest = _load_manifest()
    try:
        version = await agent_registry.register_agent(
            AgentRegistrationRequest(
                manifest=manifest,
                package_reference="agents.research_intelligence.runtime.agent:ResearchIntelligenceAgent",
            )
        )
        return {
            "status": "registered",
            "agent_id": version.agent_id,
            "agent_slug": manifest.identity.id,
            "agent_version": manifest.identity.version,
            "agent_version_id": version.id,
        }
    except ConflictError:
        agent = await agent_registry.get_agent(manifest.identity.id)
        ver = await agent_registry.get_agent_version(
            manifest.identity.id, manifest.identity.version,
        )
        return {
            "status": "already_registered",
            "agent_id": agent.id,
            "agent_slug": manifest.identity.id,
            "agent_version": manifest.identity.version,
            "agent_version_id": ver.id,
        }