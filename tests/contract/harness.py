"""
DSRT Agent Contract Compliance Harness.

A reusable test framework any DSRT Agent package must pass to be considered
C1-compliant. Future agent packages (financial_intelligence, software_engineering,
etc.) will consume this harness by providing their own `agent_factory` and
`sample_input_payload` fixtures.

Usage in an agent test module:

    from tests.contract.harness import ContractComplianceSuite

    class TestMyAgentContract(ContractComplianceSuite):
        @pytest.fixture
        def agent_factory(self):
            from agents.my_agent.runtime.agent import MyAgent
            return MyAgent

        @pytest.fixture
        def sample_input_payload(self):
            return {...}
"""

from __future__ import annotations

from typing import Any, Callable

import pytest

from core.version import AGENT_CONTRACT_VERSION, CORE_VERSION, SDK_VERSION
from schemas.domain import (
    AgentIdentity,
    AgentManifest,
    AgentPermissions,
    AgentRequirements,
)
from sdk.agent import (
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentHealth,
    AgentInitializationRequest,
    AgentInitializationResult,
    DSRTAgent,
    DSRTAgentSDK,
)


AgentFactory = Callable[[], DSRTAgent]


class ContractComplianceSuite:
    """
    Base class defining the 12 canonical DSRT Agent contract checks.
    Subclass and provide `agent_factory` + `sample_input_payload` fixtures.
    """

    # ---- Fixtures a subclass MUST override ----

    @pytest.fixture
    def agent_factory(self) -> AgentFactory:
        raise NotImplementedError(
            "Subclass must provide an `agent_factory` fixture returning a "
            "zero-argument callable that constructs a fresh agent instance."
        )

    @pytest.fixture
    def sample_input_payload(self) -> dict[str, Any]:
        raise NotImplementedError(
            "Subclass must provide a `sample_input_payload` fixture returning a "
            "minimal valid input_payload for this agent."
        )

    # ---- Helpers ----

    @pytest.fixture
    def agent(self, agent_factory: AgentFactory) -> DSRTAgent:
        return agent_factory()

    def _make_init_request(self) -> AgentInitializationRequest:
        return AgentInitializationRequest(
            execution_id="exe_contract_test",
            task_id="tsk_contract_test",
            organization_id="org_contract_test",
            agent_version_id="agv_contract_test",
            sdk_version=SDK_VERSION,
            contract_version=AGENT_CONTRACT_VERSION,
        )

    def _make_exec_request(
        self, objective: str, payload: dict[str, Any],
    ) -> AgentExecutionRequest:
        return AgentExecutionRequest(
            execution_id="exe_contract_test",
            task_id="tsk_contract_test",
            objective=objective,
            input_payload=payload,
        )

    # ---- Contract Checks (12) ----

    # C1: Identity
    def test_c1_agent_exposes_immutable_identity(self, agent: DSRTAgent):
        """Contract: agent must expose an AgentIdentity attribute."""
        assert hasattr(agent, "identity")
        assert isinstance(agent.identity, AgentIdentity)
        assert agent.identity.id
        assert agent.identity.version
        assert agent.identity.contract_version
        assert agent.identity.publisher
        assert agent.identity.category

    # C2: Manifest
    def test_c2_agent_exposes_manifest(self, agent: DSRTAgent):
        """Contract: agent must expose an AgentManifest attribute."""
        assert hasattr(agent, "manifest")
        assert isinstance(agent.manifest, AgentManifest)

    # C3: Contract version alignment
    def test_c3_agent_contract_version_matches_core(self, agent: DSRTAgent):
        """Contract: agent's declared contract_version must equal Core's."""
        assert agent.identity.contract_version == AGENT_CONTRACT_VERSION, (
            f"Agent declares contract '{agent.identity.contract_version}' "
            f"but Core exposes '{AGENT_CONTRACT_VERSION}'."
        )

    # C4: Capability declaration
    def test_c4_agent_declares_at_least_one_capability(self, agent: DSRTAgent):
        """Contract: manifest must declare at least one capability slug."""
        assert len(agent.manifest.capabilities) >= 1
        for slug in agent.manifest.capabilities:
            assert isinstance(slug, str) and slug.strip()

    # C5: Capability slug format
    def test_c5_capability_slugs_are_lowercase(self, agent: DSRTAgent):
        """Contract: capability slugs must be lowercase / dot / underscore / hyphen only."""
        import re
        pattern = re.compile(r"^[a-z][a-z0-9_.\-]*$")
        for slug in agent.manifest.capabilities:
            assert pattern.match(slug), f"Invalid capability slug: {slug!r}"

    # C6: Requirements declaration
    def test_c6_agent_declares_requirements(self, agent: DSRTAgent):
        """Contract: manifest must declare requirements (even if minimal)."""
        assert isinstance(agent.manifest.requirements, AgentRequirements)
        assert agent.manifest.requirements.minimum_core_version

    # C7: Core version compatibility
    def test_c7_agent_minimum_core_version_satisfied(self, agent: DSRTAgent):
        """Contract: agent's minimum_core_version must be <= running Core."""
        required = agent.manifest.requirements.minimum_core_version
        current = CORE_VERSION
        req_parts = [int(x) for x in required.split(".") + ["0", "0"]][:3]
        cur_parts = [int(x) for x in current.split(".") + ["0", "0"]][:3]
        assert cur_parts >= req_parts, (
            f"Agent requires Core >= {required}, but Core is {current}."
        )

    # C8: Permissions declaration
    def test_c8_agent_declares_permissions(self, agent: DSRTAgent):
        """Contract: manifest must declare permissions."""
        assert isinstance(agent.manifest.permissions, AgentPermissions)

    # C9: Health before initialize
    async def test_c9_health_reports_uninitialized(self, agent: DSRTAgent):
        """Contract: health() must be callable before initialize() and return a valid AgentHealth."""
        h = await agent.health()
        assert isinstance(h, AgentHealth)
        assert h.status in ("healthy", "degraded", "unhealthy")

    # C10: Execute before initialize is rejected
    async def test_c10_execute_before_initialize_returns_failed(
        self, agent: DSRTAgent, sample_input_payload: dict,
    ):
        """Contract: calling execute() before initialize() must return FAILED, not crash."""
        result = await agent.execute(
            self._make_exec_request("contract check", sample_input_payload)
        )
        assert isinstance(result, AgentExecutionResult)
        assert result.status == "FAILED"
        assert result.error_code is not None

    # C11: Cancel is idempotent and safe pre-initialize
    async def test_c11_cancel_is_safe_before_initialize(self, agent: DSRTAgent):
        """Contract: cancel() must be safe to call at any lifecycle stage."""
        await agent.cancel()  # Must not raise
        # Idempotency
        await agent.cancel()

    # C12: Repeated construction yields fresh state
    def test_c12_agent_factory_produces_independent_instances(
        self, agent_factory: AgentFactory,
    ):
        """Contract: agent_factory must produce independent agent instances."""
        a1 = agent_factory()
        a2 = agent_factory()
        assert a1 is not a2
        assert a1.identity.id == a2.identity.id
        assert a1.identity.version == a2.identity.version


def assert_dsrt_agent_protocol_compliance(agent: Any) -> None:
    """Ad-hoc helper: assert an object structurally satisfies DSRTAgent protocol."""
    for attr in ("identity", "manifest"):
        assert hasattr(agent, attr), f"Agent missing '{attr}' attribute."
    for method in ("initialize", "execute", "cancel", "health"):
        assert callable(getattr(agent, method, None)), (
            f"Agent missing async method '{method}'."
        )