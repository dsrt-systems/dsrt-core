"""
Compatibility Matrix Tests (C1 §46, §51).

Validates the Core / Contract / SDK / Agent version alignment matrix. When any
of these versions changes, this suite catches accidental drift.
"""

from __future__ import annotations

import pytest

from agents.research_intelligence.integration.compatibility import (
    CORE_MINIMUM_VERSION,
    EXPECTED_CONTRACT_VERSION,
    validate_compatibility,
)
from agents.research_intelligence.runtime.agent import ResearchIntelligenceAgent
from core.version import AGENT_CONTRACT_VERSION, CORE_VERSION, SDK_VERSION


class TestCompatibilityMatrix:
    def test_core_version_defined(self):
        assert CORE_VERSION
        assert len(CORE_VERSION.split(".")) == 3

    def test_agent_contract_version_defined(self):
        assert AGENT_CONTRACT_VERSION
        assert "." in AGENT_CONTRACT_VERSION

    def test_sdk_version_defined(self):
        assert SDK_VERSION
        assert len(SDK_VERSION.split(".")) == 3

    def test_research_agent_compatibility_validates(self):
        # Must not raise
        validate_compatibility()

    def test_research_agent_expects_current_contract(self):
        assert EXPECTED_CONTRACT_VERSION == AGENT_CONTRACT_VERSION

    def test_research_agent_minimum_core_below_current(self):
        agent = ResearchIntelligenceAgent()
        required = agent.manifest.requirements.minimum_core_version
        req_parts = [int(x) for x in required.split(".") + ["0", "0"]][:3]
        cur_parts = [int(x) for x in CORE_VERSION.split(".") + ["0", "0"]][:3]
        assert cur_parts >= req_parts

    def test_research_agent_contract_matches_core(self):
        agent = ResearchIntelligenceAgent()
        assert agent.identity.contract_version == AGENT_CONTRACT_VERSION

    def test_research_agent_minimum_core_matches_declaration(self):
        agent = ResearchIntelligenceAgent()
        assert (
            agent.manifest.requirements.minimum_core_version == CORE_MINIMUM_VERSION
        )