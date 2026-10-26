# core/routing/candidates/generator.py
"""
C9 Candidate Generator (§13–16).

Generates all possible route candidates from eligible agents,
models, and worlds.  Each candidate is a complete execution
configuration that will later be filtered by the PolicyEngine.

Design:
  - Broad generation, narrow selection.
  - Basic compatibility pre-filtering (model supports required
    capabilities, world provides required tools).
  - Every candidate carries capability_fit and constraint_fit
    metadata for downstream scoring.
"""

from __future__ import annotations

import uuid
from typing import Any

from core.routing.contracts import (
    AgentCapabilityProfile,
    CapabilityMatchSummary,
    ModelCapabilityProfile,
    RouteCandidate,
    TaskRequirements,
)
from core.routing.enums import EligibilityStatus


def _new_candidate_id() -> str:
    return f"cand_{uuid.uuid4().hex[:12]}"


class CandidateGenerator:
    """Generates route candidates from capability match results (§13).

    Usage::

        gen = CandidateGenerator()
        candidates = gen.generate(
            requirements=reqs,
            eligible_agents=[agent_profile_a, agent_profile_b],
            eligible_models=[model_profile_x, model_profile_y],
            available_worlds=[{"world_id": "w1", "world_version_id": "v1", "tools": [...]}],
        )
    """

    def generate(
        self,
        requirements: TaskRequirements,
        eligible_agents: list[AgentCapabilityProfile],
        eligible_models: list[ModelCapabilityProfile],
        available_worlds: list[dict[str, Any]] | None = None,
        agent_matches: dict[str, CapabilityMatchSummary] | None = None,
        model_matches: dict[str, CapabilityMatchSummary] | None = None,
    ) -> list[RouteCandidate]:
        """Generate all valid route candidates.

        Parameters
        ----------
        requirements:
            The structured task requirements.
        eligible_agents:
            Agent profiles that satisfy all required capabilities.
        eligible_models:
            Model profiles that satisfy all required capabilities.
        available_worlds:
            Optional list of world dicts with keys:
            ``world_id``, ``world_version_id``, ``tools``.
            If ``None``, a single ``None``-world candidate is generated.
        agent_matches:
            Optional pre-computed match summaries keyed by agent_id.
        model_matches:
            Optional pre-computed match summaries keyed by model_id.

        Returns
        -------
        list[RouteCandidate]
            All generated candidates (eligible by default; the
            PolicyEngine will reject those violating hard constraints).
        """
        agent_matches = agent_matches or {}
        model_matches = model_matches or {}

        # Normalise worlds
        if not available_worlds:
            worlds: list[dict[str, Any]] = [
                {"world_id": None, "world_version_id": None, "tools": []}
            ]
        else:
            worlds = available_worlds

        candidates: list[RouteCandidate] = []

        for agent in eligible_agents:
            for model in eligible_models:
                for world in worlds:
                    # ── Tool compatibility check ──────────────
                    world_tools: list[str] = world.get("tools", [])
                    required_tools = set(requirements.required_tools)
                    available_tools = set(world_tools)

                    tools_ok = required_tools.issubset(available_tools) if required_tools else True

                    # Merge preferred tools that are available
                    selected_tools = list(
                        required_tools | (
                            set(requirements.preferred_tools) & available_tools
                        )
                    )

                    # ── Build capability_fit ──────────────────
                    cap_fit: dict[str, bool] = {}
                    a_match = agent_matches.get(agent.agent_id)
                    if a_match:
                        for m in a_match.matches:
                            cap_fit[f"agent:{m.capability_id}"] = m.matched

                    m_match = model_matches.get(model.model_id)
                    if m_match:
                        for m in m_match.matches:
                            cap_fit[f"model:{m.capability_id}"] = m.matched

                    # ── Build constraint_fit ──────────────────
                    constraint_fit: dict[str, bool] = {
                        "tools_available": tools_ok,
                    }

                    # Check context window
                    if requirements.resources.max_input_tokens is not None:
                        ctx = model.limits.context_tokens
                        constraint_fit["context_window"] = (
                            ctx is not None
                            and ctx >= requirements.resources.max_input_tokens
                        )
                    else:
                        constraint_fit["context_window"] = True

                    # Check output token limit
                    if requirements.resources.max_output_tokens is not None:
                        out = model.limits.max_output_tokens
                        constraint_fit["output_tokens"] = (
                            out is not None
                            and out >= requirements.resources.max_output_tokens
                        )
                    else:
                        constraint_fit["output_tokens"] = True

                    # ── Create candidate ──────────────────────
                    candidate = RouteCandidate(
                        candidate_id=_new_candidate_id(),
                        agent_id=agent.agent_id,
                        agent_version_id=agent.agent_version_id,
                        model_id=model.model_id,
                        model_version_id=model.model_version_id,
                        provider_id=model.provider_id,
                        world_id=world.get("world_id"),
                        world_version_id=world.get("world_version_id"),
                        tools=selected_tools,
                        capability_fit=cap_fit,
                        constraint_fit=constraint_fit,
                    )

                    # Pre-reject if tools are missing (hard constraint)
                    if not tools_ok:
                        from core.routing.enums import RejectionCategory
                        candidate.reject(
                            RejectionCategory.TOOL_UNAVAILABLE,
                            f"World missing required tools: "
                            f"{required_tools - available_tools}",
                        )

                    candidates.append(candidate)

        return candidates

    def generate_single_model(
        self,
        requirements: TaskRequirements,
        agent: AgentCapabilityProfile,
        model: ModelCapabilityProfile,
        world: dict[str, Any] | None = None,
    ) -> RouteCandidate:
        """Convenience: generate a single candidate for testing."""
        worlds = [world] if world else None
        results = self.generate(
            requirements=requirements,
            eligible_agents=[agent],
            eligible_models=[model],
            available_worlds=worlds,
        )
        return results[0]