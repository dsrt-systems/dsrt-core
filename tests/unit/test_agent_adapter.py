"""Unit tests for the Core-side AgentAdapter (C1 §16)."""

from __future__ import annotations

import pytest

from core.agents.adapter import AgentAdapter
from core.api.errors.exceptions import DSRTError, ValidationError
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
)


def _identity() -> AgentIdentity:
    return AgentIdentity(
        id="mock_agent",
        name="Mock Agent",
        version="1.0.0",
        contract_version="1.0",
        publisher="dsrt",
        category="test",
    )


def _manifest() -> AgentManifest:
    return AgentManifest(
        identity=_identity(),
        capabilities=["cap_x"],
        requirements=AgentRequirements(minimum_core_version="1.0.0"),
        permissions=AgentPermissions(),
    )


class _MockAgent:
    def __init__(self, execute_impl=None, init_ready=True, raise_on_init=False):
        self.identity = _identity()
        self.manifest = _manifest()
        self._execute_impl = execute_impl
        self._init_ready = init_ready
        self._raise_on_init = raise_on_init
        self.cancelled = False

    async def initialize(self, sdk, request):
        if self._raise_on_init:
            raise RuntimeError("init boom")
        return AgentInitializationResult(
            status="READY" if self._init_ready else "FAILED"
        )

    async def execute(self, request):
        if self._execute_impl is not None:
            return await self._execute_impl(request)
        return AgentExecutionResult(status="COMPLETED")

    async def cancel(self):
        self.cancelled = True

    async def health(self):
        return AgentHealth(status="healthy")


def _init_request() -> AgentInitializationRequest:
    return AgentInitializationRequest(
        execution_id="exe_1", task_id="tsk_1", organization_id="org_1",
        agent_version_id="agv_1", sdk_version="1.0.0", contract_version="1.0",
    )


def _exec_request() -> AgentExecutionRequest:
    return AgentExecutionRequest(
        execution_id="exe_1", task_id="tsk_1", objective="do a thing",
    )


class TestAgentAdapter:
    async def test_execute_requires_initialize_first(self):
        adapter = AgentAdapter(_MockAgent())
        with pytest.raises(ValidationError, match="initialized"):
            await adapter.execute(_exec_request())

    async def test_initialize_then_execute(self):
        adapter = AgentAdapter(_MockAgent())
        await adapter.initialize(sdk=None, request=_init_request())  # type: ignore[arg-type]
        result = await adapter.execute(_exec_request())
        assert result.status == "COMPLETED"

    async def test_initialize_failure_wrapped_as_dsrt_error(self):
        adapter = AgentAdapter(_MockAgent(raise_on_init=True))
        with pytest.raises(DSRTError, match="failed to initialize"):
            await adapter.initialize(sdk=None, request=_init_request())  # type: ignore[arg-type]

    async def test_non_ready_init_status_raises(self):
        adapter = AgentAdapter(_MockAgent(init_ready=False))
        with pytest.raises(DSRTError, match="non-READY"):
            await adapter.initialize(sdk=None, request=_init_request())  # type: ignore[arg-type]

    async def test_execute_exception_normalized_to_failed_result(self):
        async def _boom(_req):
            raise RuntimeError("execute boom")

        adapter = AgentAdapter(_MockAgent(execute_impl=_boom))
        await adapter.initialize(sdk=None, request=_init_request())  # type: ignore[arg-type]
        result = await adapter.execute(_exec_request())
        assert result.status == "FAILED"
        assert result.error_code == "AGENT_EXECUTION_FAILED"
        assert "execute boom" in (result.error_message or "")

    async def test_cancel_before_execute_returns_cancelled_result(self):
        adapter = AgentAdapter(_MockAgent())
        await adapter.initialize(sdk=None, request=_init_request())  # type: ignore[arg-type]
        await adapter.cancel()
        result = await adapter.execute(_exec_request())
        assert result.status == "CANCELLED"
        assert result.error_code == "EXECUTION_CANCELLED"

    async def test_health_swallows_agent_exceptions(self):
        agent = _MockAgent()

        async def _boom():
            raise RuntimeError("health boom")

        agent.health = _boom  # type: ignore[method-assign]
        adapter = AgentAdapter(agent)
        h = await adapter.health()
        assert h.status == "unhealthy"
        assert "health boom" in h.details.get("error", "")