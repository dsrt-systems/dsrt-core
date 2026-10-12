"""Tests for agent manifest validation logic."""

import pytest

from core.agents.validator import AgentValidator
from core.api.errors.exceptions import ValidationError
from schemas.domain import AgentManifest


def _valid_manifest() -> dict:
    return {
        "identity": {
            "id": "research_intelligence",
            "name": "Research Intelligence",
            "version": "1.0.0",
            "contract_version": "1.0",
            "publisher": "dsrt",
            "category": "research",
        },
        "capabilities": ["research_planning"],
        "requirements": {
            "minimum_core_version": "1.0.0",
            "required_capabilities": [],
            "optional_capabilities": [],
            "required_tools": [],
            "optional_tools": [],
        },
        "permissions": {},
    }


class DummyCapRegistry:
    def __init__(self, existing_caps: list[str]):
        self._caps = set(existing_caps)

    async def validate_capabilities_exist(self, slugs: list[str]) -> list[str]:
        return [s for s in slugs if s not in self._caps]


@pytest.mark.asyncio
async def test_validator_accepts_valid_manifest():
    cap_reg = DummyCapRegistry(["research_planning"])
    validator = AgentValidator(cap_reg)
    manifest = AgentManifest(**_valid_manifest())
    await validator.validate_manifest(manifest)  # Should not raise


@pytest.mark.asyncio
async def test_validator_rejects_incompatible_contract_version():
    cap_reg = DummyCapRegistry(["research_planning"])
    validator = AgentValidator(cap_reg)
    data = _valid_manifest()
    data["identity"]["contract_version"] = "99.0"
    manifest = AgentManifest(**data)
    with pytest.raises(ValidationError, match="contract version"):
        await validator.validate_manifest(manifest)


@pytest.mark.asyncio
async def test_validator_rejects_unregistered_capability():
    cap_reg = DummyCapRegistry([])  # No caps exist
    validator = AgentValidator(cap_reg)
    manifest = AgentManifest(**_valid_manifest())
    with pytest.raises(ValidationError, match="unregistered capabilities"):
        await validator.validate_manifest(manifest)