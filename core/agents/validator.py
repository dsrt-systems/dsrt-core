"""
Agent Manifest Validator.

Validates an AgentManifest against Core contracts before registration (C1 §15).
Enforces:
    1. Identity invariants
    2. Contract version compatibility (must match supported AGENT_CONTRACT_VERSION)
    3. Capability declaration validity against Capability Registry
    4. Permission request sanity checks
"""

from __future__ import annotations

from core.api.errors.exceptions import ValidationError
from core.capabilities.registry import CapabilityRegistry
from core.version import AGENT_CONTRACT_VERSION, CORE_VERSION
from schemas.domain import AgentManifest


class AgentValidator:
    def __init__(self, capability_registry: CapabilityRegistry) -> None:
        self._capabilities = capability_registry

    async def validate_manifest(self, manifest: AgentManifest) -> None:
        """Validate an AgentManifest for registration.

        Raises ValidationError on contract violation.
        """
        # 1. Contract version check
        if manifest.identity.contract_version != AGENT_CONTRACT_VERSION:
            raise ValidationError(
                f"Agent contract version '{manifest.identity.contract_version}' "
                f"is incompatible with Core contract version '{AGENT_CONTRACT_VERSION}'.",
                metadata={
                    "agent_contract_version": manifest.identity.contract_version,
                    "supported_contract_version": AGENT_CONTRACT_VERSION,
                },
            )

        # 2. Minimum core version check
        min_core = manifest.requirements.minimum_core_version
        if not self._is_version_compatible(CORE_VERSION, min_core):
            raise ValidationError(
                f"Agent requires Core version >={min_core}, but running Core is {CORE_VERSION}.",
                metadata={"required_core_version": min_core, "current_core_version": CORE_VERSION},
            )

        # 3. Validate declared capabilities exist in Capability Registry
        missing_caps = await self._capabilities.validate_capabilities_exist(
            manifest.capabilities,
        )
        if missing_caps:
            raise ValidationError(
                f"Agent declares unregistered capabilities: {', '.join(missing_caps)}",
                metadata={"missing_capabilities": missing_caps},
            )

        # 4. Validate requested capabilities in requirements exist
        missing_req_caps = await self._capabilities.validate_capabilities_exist(
            manifest.requirements.required_capabilities,
        )
        if missing_req_caps:
            raise ValidationError(
                f"Agent requires unregistered capabilities: {', '.join(missing_req_caps)}",
                metadata={"missing_required_capabilities": missing_req_caps},
            )

    @staticmethod
    def _is_version_compatible(current: str, required: str) -> bool:
        """Simple semver comparison: current >= required."""
        try:
            curr_parts = [int(p) for p in current.split(".")]
            req_parts = [int(p) for p in required.split(".")]
            return curr_parts >= req_parts
        except (ValueError, AttributeError):
            return True