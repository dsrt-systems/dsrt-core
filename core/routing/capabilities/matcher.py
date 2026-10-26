# core/routing/capabilities/matcher.py
"""
C9 Capability Matcher (§9–10).

Matches ``TaskRequirements`` against agent and model capability
profiles to determine which entities can satisfy the task.
"""

from __future__ import annotations

from core.routing.contracts import (
    AgentCapabilityProfile,
    CapabilityMatchResult,
    CapabilityMatchSummary,
    CapabilityRequirement,
    ModelCapabilityProfile,
    TaskRequirements,
)
from core.routing.enums import (
    CapabilityImportance,
    ModelCapabilityType,
    ProficiencyLevel,
)


# ── Mapping from generic capability IDs to ModelCapabilityType ────

_CAP_TO_MODEL_TYPE: dict[str, ModelCapabilityType] = {
    "reasoning": ModelCapabilityType.REASONING,
    "structured_output": ModelCapabilityType.STRUCTURED_OUTPUT,
    "tool_use": ModelCapabilityType.TOOL_USE,
    "vision": ModelCapabilityType.VISION,
    "long_context": ModelCapabilityType.LONG_CONTEXT,
    "code_generation": ModelCapabilityType.CODE_GENERATION,
    "streaming": ModelCapabilityType.STREAMING,
    "function_calling": ModelCapabilityType.FUNCTION_CALLING,
    "multi_modal": ModelCapabilityType.MULTI_MODAL,
    "embedding": ModelCapabilityType.EMBEDDING,
}


class CapabilityMatcher:
    """Matches task requirements against entity capability profiles.

    Usage::

        matcher = CapabilityMatcher()
        summary = matcher.match_agent(requirements, agent_profile)
        if summary.all_required_met:
            ...
    """

    # ── Agent matching ────────────────────────────────────────────

    def match_agent(
        self,
        requirements: TaskRequirements,
        profile: AgentCapabilityProfile,
    ) -> CapabilityMatchSummary:
        """Match task requirements against an agent capability profile."""
        matches: list[CapabilityMatchResult] = []

        for req in requirements.capabilities:
            entry = profile.get_capability(req.capability_id)
            if entry is not None:
                # Check minimum version if specified
                version_ok = True
                if req.minimum_version and entry.version:
                    version_ok = entry.version >= req.minimum_version

                matches.append(
                    CapabilityMatchResult(
                        capability_id=req.capability_id,
                        required=req.required,
                        matched=version_ok,
                        proficiency=entry.proficiency,
                        detail=(
                            f"proficiency={entry.proficiency.value}"
                            + ("" if version_ok else f", version {entry.version} < {req.minimum_version}")
                        ),
                    )
                )
            else:
                matches.append(
                    CapabilityMatchResult(
                        capability_id=req.capability_id,
                        required=req.required,
                        matched=False,
                        detail="capability not declared by agent",
                    )
                )

        return CapabilityMatchSummary(
            entity_id=profile.agent_id,
            entity_type="agent",
            matches=matches,
        )

    # ── Model matching ────────────────────────────────────────────

    def match_model(
        self,
        requirements: TaskRequirements,
        profile: ModelCapabilityProfile,
    ) -> CapabilityMatchSummary:
        """Match task requirements against a model capability profile."""
        matches: list[CapabilityMatchResult] = []

        for req in requirements.capabilities:
            model_cap_type = _CAP_TO_MODEL_TYPE.get(req.capability_id)

            if model_cap_type is not None:
                has_cap = profile.has_capability(model_cap_type)
                matches.append(
                    CapabilityMatchResult(
                        capability_id=req.capability_id,
                        required=req.required,
                        matched=has_cap,
                        detail=(
                            f"model capability {model_cap_type.value}"
                            + (" supported" if has_cap else " not supported")
                        ),
                    )
                )
            else:
                # Capability not mappable to model type — treat as
                # matched if not required, unmatched if required
                # (agent-level capabilities like "web_research" are
                # not model capabilities)
                if req.required:
                    matches.append(
                        CapabilityMatchResult(
                            capability_id=req.capability_id,
                            required=True,
                            matched=False,
                            detail="not a model-level capability",
                        )
                    )
                # If optional/preferred, skip — not a model concern

        # Also check resource constraints against model limits
        if requirements.resources.max_input_tokens is not None:
            if (
                profile.limits.context_tokens is not None
                and profile.limits.context_tokens
                < requirements.resources.max_input_tokens
            ):
                matches.append(
                    CapabilityMatchResult(
                        capability_id="context_window",
                        required=True,
                        matched=False,
                        detail=(
                            f"model context {profile.limits.context_tokens} "
                            f"< required {requirements.resources.max_input_tokens}"
                        ),
                    )
                )

        return CapabilityMatchSummary(
            entity_id=profile.model_id,
            entity_type="model",
            matches=matches,
        )

    # ── Batch matching ────────────────────────────────────────────

    def match_agents(
        self,
        requirements: TaskRequirements,
        profiles: list[AgentCapabilityProfile],
    ) -> list[CapabilityMatchSummary]:
        """Match requirements against multiple agent profiles."""
        return [
            self.match_agent(requirements, p) for p in profiles
        ]

    def match_models(
        self,
        requirements: TaskRequirements,
        profiles: list[ModelCapabilityProfile],
    ) -> list[CapabilityMatchSummary]:
        """Match requirements against multiple model profiles."""
        return [
            self.match_model(requirements, p) for p in profiles
        ]

    def filter_eligible_agents(
        self,
        requirements: TaskRequirements,
        profiles: list[AgentCapabilityProfile],
    ) -> list[AgentCapabilityProfile]:
        """Return only agents that satisfy all required capabilities."""
        return [
            p
            for p in profiles
            if self.match_agent(requirements, p).all_required_met
        ]

    def filter_eligible_models(
        self,
        requirements: TaskRequirements,
        profiles: list[ModelCapabilityProfile],
    ) -> list[ModelCapabilityProfile]:
        """Return only models that satisfy all required capabilities."""
        return [
            p
            for p in profiles
            if self.match_model(requirements, p).all_required_met
        ]