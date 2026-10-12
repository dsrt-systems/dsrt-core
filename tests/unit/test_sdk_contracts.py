"""Unit tests for the DSRT Agent SDK contract dataclasses."""

from __future__ import annotations

import pytest

from sdk.agent import (
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentHealth,
    AgentInitializationRequest,
    AgentInitializationResult,
    SDKAgentContext,
    SDKArtifact,
    SDKMemoryRecord,
    SDKModelRequest,
    SDKModelResponse,
    SDKModelUsage,
    SDKToolResult,
    SDKVerificationResult,
)


class TestSDKDataclasses:
    def test_model_request_defaults(self):
        req = SDKModelRequest(
            purpose="analysis",
            messages=[{"role": "user", "content": "x"}],
        )
        assert req.purpose == "analysis"
        assert req.temperature is None
        assert req.metadata == {}

    def test_model_response_defaults(self):
        res = SDKModelResponse(output="ok")
        assert res.finish_reason == "completed"
        assert res.usage.total_tokens == 0

    def test_model_request_is_frozen(self):
        req = SDKModelRequest(purpose="p", messages=[])
        with pytest.raises(Exception):
            req.purpose = "changed"  # type: ignore[misc]

    def test_tool_result_defaults(self):
        res = SDKToolResult(
            tool_slug="web.search", status="SUCCESS", output=[],
        )
        assert res.error_code is None
        assert res.duration_ms == 0

    def test_agent_context_defaults(self):
        ctx = SDKAgentContext(
            execution_id="exe_1",
            task_id="tsk_1",
            organization_id="org_1",
            user_id="usr_1",
            agent_slug="research",
            agent_version="1.0.0",
            objective="Research X",
        )
        assert ctx.input_payload == {}
        assert ctx.working_state == {}
        assert ctx.configuration_hash == ""

    def test_memory_record_defaults(self):
        m = SDKMemoryRecord(memory_type="semantic", content="Fact")
        assert m.scope == "project"
        assert m.id is None

    def test_artifact_defaults(self):
        a = SDKArtifact(
            id="art_1",
            name="report.md",
            artifact_type="DOCUMENT",
            mime_type="text/markdown",
            size_bytes=100,
            content_hash="abc",
        )
        assert a.metadata == {}

    def test_verification_result_defaults(self):
        r = SDKVerificationResult(
            subject_id="s", policy_id="p", status="INCONCLUSIVE",
        )
        assert r.evidence_refs == []


class TestAgentContractDataclasses:
    def test_init_request(self):
        req = AgentInitializationRequest(
            execution_id="e", task_id="t", organization_id="o",
            agent_version_id="v", sdk_version="1.0.0", contract_version="1.0",
        )
        assert req.contract_version == "1.0"

    def test_init_result_defaults(self):
        r = AgentInitializationResult()
        assert r.status == "READY"

    def test_execution_result_defaults(self):
        r = AgentExecutionResult()
        assert r.status == "COMPLETED"
        assert r.error_code is None

    def test_health_defaults(self):
        h = AgentHealth()
        assert h.status == "healthy"

    def test_execution_request_defaults(self):
        r = AgentExecutionRequest(
            execution_id="e", task_id="t", objective="o",
        )
        assert r.input_payload == {}