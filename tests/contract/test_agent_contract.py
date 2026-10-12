"""
Research Intelligence Agent — Contract Compliance Tests.

These tests inherit the entire ContractComplianceSuite. Any future DSRT agent
package should create an equivalent module wiring its own agent_factory.
"""

from __future__ import annotations

from typing import Any

import pytest

from agents.research_intelligence.runtime.agent import ResearchIntelligenceAgent
from tests.contract.harness import (
    ContractComplianceSuite,
    assert_dsrt_agent_protocol_compliance,
)


class TestResearchIntelligenceContract(ContractComplianceSuite):
    """Research Intelligence Agent v1.0 must pass every C1 contract check."""

    @pytest.fixture
    def agent_factory(self):
        return ResearchIntelligenceAgent

    @pytest.fixture
    def sample_input_payload(self) -> dict[str, Any]:
        return {
            "questions": ["What is X?"],
            "evidence": [
                {
                    "source_title": "Test Source",
                    "passage": "Test passage supporting the claim.",
                    "claim": "Test claim about X.",
                }
            ],
        }


class TestResearchAgentStructuralProtocol:
    """Ad-hoc structural checks beyond the shared suite."""

    def test_research_agent_satisfies_dsrt_agent_protocol(self):
        agent = ResearchIntelligenceAgent()
        assert_dsrt_agent_protocol_compliance(agent)

    def test_research_agent_declares_expected_capabilities(self):
        agent = ResearchIntelligenceAgent()
        expected = {
            "research_planning",
            "evidence_synthesis",
            "report_generation",
        }
        declared = set(agent.manifest.capabilities)
        assert expected.issubset(declared), (
            f"Missing expected capabilities: {expected - declared}"
        )

    def test_research_agent_permissions_are_conservative(self):
        agent = ResearchIntelligenceAgent()
        p = agent.manifest.permissions
        assert p.browser.access is False
        assert p.external_actions.access is False