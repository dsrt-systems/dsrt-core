"""
Unit tests for C2.1 Model Fabric contracts.

These tests validate that the canonical provider-neutral contracts behave
correctly in isolation — before any provider adapter code exists. They lock
the frozen interface shape that every provider adapter must satisfy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from schemas.domain import (
    CostBreakdown,
    CredentialReference,
    CredentialStatus,
    CredentialType,
    FinishReason,
    MessageContentPart,
    MessageContentType,
    MessageRole,
    ModelError,
    ModelErrorCode,
    ModelMessage,
    ModelModality,
    ModelPolicy,
    ModelRequest,
    ModelRequirements,
    ModelResponse,
    ProviderHealth,
    ProviderHealthStatus,
    ReasoningEffort,
    RejectedCandidate,
    RetryClassification,
    RoutingDecision,
    RoutingReasonCode,
    StreamEvent,
    StreamEventType,
    TokenCountRequest,
    TokenCountResponse,
    ToolCall,
    ToolCallMode,
    ToolDefinition,
    ToolParameterSchema,
    Usage,
)


# ---------------------------------------------------------------------------
# Message content
# ---------------------------------------------------------------------------


class TestModelMessage:
    def test_simple_text_message(self):
        msg = ModelMessage(role=MessageRole.USER, content="Hello")
        assert msg.role == MessageRole.USER
        assert msg.content == "Hello"

    def test_multi_part_content(self):
        msg = ModelMessage(
            role=MessageRole.USER,
            content=[
                MessageContentPart(type=MessageContentType.TEXT, text="Describe this:"),
                MessageContentPart(
                    type=MessageContentType.IMAGE_URL,
                    image_url="https://example.org/img.png",
                ),
            ],
        )
        assert isinstance(msg.content, list)
        assert len(msg.content) == 2
        assert msg.content[1].type == MessageContentType.IMAGE_URL

    def test_empty_string_content_rejected(self):
        with pytest.raises(ValidationError):
            ModelMessage(role=MessageRole.USER, content="   ")

    def test_empty_list_content_rejected(self):
        with pytest.raises(ValidationError):
            ModelMessage(role=MessageRole.USER, content=[])

    def test_tool_message(self):
        msg = ModelMessage(
            role=MessageRole.TOOL,
            content="result data",
            tool_call_id="call_123",
        )
        assert msg.tool_call_id == "call_123"


class TestMessageContentPart:
    def test_text_part(self):
        part = MessageContentPart(type=MessageContentType.TEXT, text="hi")
        assert part.text == "hi"

    def test_image_url_part(self):
        part = MessageContentPart(
            type=MessageContentType.IMAGE_URL,
            image_url="https://example.org/x.png",
        )
        assert part.image_url is not None

    def test_tool_result_part(self):
        part = MessageContentPart(
            type=MessageContentType.TOOL_RESULT,
            tool_call_id="call_1",
            tool_result={"status": "ok", "value": 42},
        )
        assert part.tool_result == {"status": "ok", "value": 42}


# ---------------------------------------------------------------------------
# Tool definitions and calls
# ---------------------------------------------------------------------------


class TestToolDefinition:
    def test_valid_tool_definition(self):
        tool = ToolDefinition(
            name="web_search",
            description="Search the web",
            parameters=ToolParameterSchema(
                properties={"query": {"type": "string"}},
                required=["query"],
            ),
        )
        assert tool.name == "web_search"
        assert "query" in tool.parameters.properties

    def test_invalid_name_rejected(self):
        with pytest.raises(ValidationError):
            ToolDefinition(name="web search!", description="x")

    def test_empty_description_rejected(self):
        with pytest.raises(ValidationError):
            ToolDefinition(name="x", description="")


class TestToolCall:
    def test_valid_tool_call(self):
        call = ToolCall(id="call_abc", name="web_search", arguments={"query": "x"})
        assert call.id == "call_abc"
        assert call.arguments == {"query": "x"}

    def test_tool_call_is_frozen(self):
        call = ToolCall(id="c", name="n", arguments={})
        with pytest.raises(Exception):
            call.name = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Model requirements / policy
# ---------------------------------------------------------------------------


class TestModelRequirements:
    def test_defaults_are_empty(self):
        r = ModelRequirements()
        assert r.required_capabilities == []
        assert r.minimum_context_tokens is None

    def test_rejects_zero_context_requirement(self):
        with pytest.raises(ValidationError):
            ModelRequirements(minimum_context_tokens=0)

    def test_rejects_negative_max_cost(self):
        with pytest.raises(ValidationError):
            ModelRequirements(maximum_cost_usd=Decimal("-1"))


class TestModelPolicy:
    def test_defaults_are_permissive(self):
        p = ModelPolicy()
        assert p.allow_byok is True
        assert p.allow_managed is True
        assert p.blocked_models == []

    def test_blocked_wins(self):
        p = ModelPolicy(
            allowed_models=["m1", "m2"],
            blocked_models=["m2"],
        )
        assert "m2" in p.blocked_models  # Enforcement is in the Router (C2.6); policy records intent.


# ---------------------------------------------------------------------------
# ModelRequest
# ---------------------------------------------------------------------------


class TestModelRequest:
    def _base_request(self) -> dict:
        return dict(
            request_id="req_abc",
            execution_id="exe_abc",
            task_id="tsk_abc",
            organization_id="org_abc",
            purpose="research_analysis",
            messages=[ModelMessage(role=MessageRole.USER, content="hi")],
        )

    def test_minimal_valid_request(self):
        req = ModelRequest(**self._base_request())
        assert req.purpose == "research_analysis"
        assert req.attempt == 1
        assert req.modalities == [ModelModality.TEXT]
        assert req.stream is False

    def test_rejects_empty_messages(self):
        args = self._base_request()
        args["messages"] = []
        with pytest.raises(ValidationError):
            ModelRequest(**args)

    def test_rejects_temperature_out_of_range(self):
        args = self._base_request()
        args["temperature"] = 2.5
        with pytest.raises(ValidationError):
            ModelRequest(**args)

    def test_rejects_negative_max_output(self):
        args = self._base_request()
        args["max_output_tokens"] = 0
        with pytest.raises(ValidationError):
            ModelRequest(**args)

    def test_tool_calling_fields(self):
        args = self._base_request()
        args["tools"] = [
            ToolDefinition(name="web_search", description="search"),
        ]
        args["tool_choice"] = "auto"
        args["tool_call_mode"] = ToolCallMode.PARALLEL
        req = ModelRequest(**args)
        assert req.tool_call_mode == ToolCallMode.PARALLEL

    def test_reasoning_effort(self):
        args = self._base_request()
        args["reasoning_effort"] = ReasoningEffort.HIGH
        req = ModelRequest(**args)
        assert req.reasoning_effort == ReasoningEffort.HIGH

    def test_multimodal_request(self):
        args = self._base_request()
        args["modalities"] = [ModelModality.TEXT, ModelModality.IMAGE]
        args["messages"] = [
            ModelMessage(
                role=MessageRole.USER,
                content=[
                    MessageContentPart(type=MessageContentType.TEXT, text="describe"),
                    MessageContentPart(
                        type=MessageContentType.IMAGE_URL,
                        image_url="https://x.y/img.png",
                    ),
                ],
            )
        ]
        req = ModelRequest(**args)
        assert ModelModality.IMAGE in req.modalities

    def test_metadata_defaults_empty(self):
        req = ModelRequest(**self._base_request())
        assert req.metadata == {}


# ---------------------------------------------------------------------------
# Usage, Cost, Response
# ---------------------------------------------------------------------------


class TestUsage:
    def test_defaults_all_none(self):
        u = Usage()
        assert u.input_tokens is None
        assert u.estimated_cost_usd is None
        assert u.provider_reported_cost_usd is None

    def test_estimated_and_reported_remain_distinct(self):
        u = Usage(
            input_tokens=100,
            output_tokens=200,
            estimated_cost_usd=Decimal("0.001"),
            provider_reported_cost_usd=Decimal("0.0012"),
        )
        # Invariant: these are and remain separate fields.
        assert u.estimated_cost_usd != u.provider_reported_cost_usd

    def test_is_frozen(self):
        u = Usage(input_tokens=10)
        with pytest.raises(Exception):
            u.input_tokens = 20  # type: ignore[misc]

    def test_rejects_negative_tokens(self):
        with pytest.raises(ValidationError):
            Usage(input_tokens=-1)


class TestCostBreakdown:
    def test_all_separate_fields(self):
        c = CostBreakdown(
            provider_cost_usd=Decimal("0.01"),
            estimated_cost_usd=Decimal("0.009"),
            dsrt_platform_cost_usd=Decimal("0.001"),
            customer_charge_usd=Decimal("0.015"),
        )
        assert c.provider_cost_usd != c.estimated_cost_usd
        assert c.customer_charge_usd > (c.provider_cost_usd or Decimal(0))


class TestModelResponse:
    def test_valid_response(self):
        r = ModelResponse(
            request_id="req_1",
            model_id="mdl_1",
            provider_id="prv_1",
            model_identifier="gpt-neutral-1",
            output="hello",
            latency_ms=42,
            created_at=datetime.now(timezone.utc),
        )
        assert r.finish_reason == FinishReason.COMPLETED
        assert r.tool_calls == []

    def test_response_is_frozen(self):
        r = ModelResponse(
            request_id="r", model_id="m", provider_id="p",
            model_identifier="x", latency_ms=1,
            created_at=datetime.now(timezone.utc),
        )
        with pytest.raises(Exception):
            r.output = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Token count
# ---------------------------------------------------------------------------


class TestTokenCount:
    def test_token_count_request(self):
        req = TokenCountRequest(
            messages=[ModelMessage(role=MessageRole.USER, content="hi")],
        )
        assert len(req.messages) == 1

    def test_token_count_response_defaults(self):
        resp = TokenCountResponse(
            input_tokens=10, total_tokens=10, model_identifier="x",
        )
        assert resp.is_estimate is True
        assert resp.tool_tokens == 0


# ---------------------------------------------------------------------------
# Stream events
# ---------------------------------------------------------------------------


class TestStreamEvent:
    def test_text_delta_event(self):
        ev = StreamEvent(
            request_id="r",
            event_type=StreamEventType.TEXT_DELTA,
            sequence=1,
            text_delta="hello",
            created_at=datetime.now(timezone.utc),
        )
        assert ev.text_delta == "hello"

    def test_terminal_completed_event(self):
        ev = StreamEvent(
            request_id="r",
            event_type=StreamEventType.STREAM_COMPLETED,
            sequence=99,
            finish_reason=FinishReason.COMPLETED,
            created_at=datetime.now(timezone.utc),
        )
        assert ev.finish_reason == FinishReason.COMPLETED

    def test_failed_event_with_error(self):
        ev = StreamEvent(
            request_id="r",
            event_type=StreamEventType.STREAM_FAILED,
            sequence=50,
            error_code=ModelErrorCode.PROVIDER_TIMEOUT,
            error_message="provider timed out",
            created_at=datetime.now(timezone.utc),
        )
        assert ev.error_code == ModelErrorCode.PROVIDER_TIMEOUT

    def test_sequence_must_be_non_negative(self):
        with pytest.raises(ValidationError):
            StreamEvent(
                request_id="r",
                event_type=StreamEventType.TEXT_DELTA,
                sequence=-1,
                created_at=datetime.now(timezone.utc),
            )


# ---------------------------------------------------------------------------
# Provider health
# ---------------------------------------------------------------------------


class TestProviderHealth:
    def test_healthy_observation(self):
        h = ProviderHealth(
            provider_id="prv_1",
            status=ProviderHealthStatus.HEALTHY,
            observed_at=datetime.now(timezone.utc),
            avg_latency_ms=120.5,
            error_rate=0.0,
        )
        assert h.status == ProviderHealthStatus.HEALTHY

    def test_rate_limited_observation(self):
        now = datetime.now(timezone.utc)
        h = ProviderHealth(
            provider_id="prv_1",
            status=ProviderHealthStatus.RATE_LIMITED,
            observed_at=now,
            rate_limit_remaining=0,
            rate_limit_reset_at=now,
        )
        assert h.status == ProviderHealthStatus.RATE_LIMITED

    def test_error_rate_bounded(self):
        with pytest.raises(ValidationError):
            ProviderHealth(
                provider_id="p",
                status=ProviderHealthStatus.DEGRADED,
                observed_at=datetime.now(timezone.utc),
                error_rate=1.5,
            )


# ---------------------------------------------------------------------------
# Model error
# ---------------------------------------------------------------------------


class TestModelError:
    def test_retryable_timeout(self):
        err = ModelError(
            code=ModelErrorCode.PROVIDER_TIMEOUT,
            message="provider timed out after 30s",
            retry_classification=RetryClassification.RETRYABLE_WITH_BACKOFF,
            provider_id="prv_1",
            request_id="req_1",
        )
        assert err.retry_classification == RetryClassification.RETRYABLE_WITH_BACKOFF

    def test_non_retryable_credential(self):
        err = ModelError(
            code=ModelErrorCode.CREDENTIAL_INVALID,
            message="API key invalid",
            retry_classification=RetryClassification.NOT_RETRYABLE,
        )
        assert err.retry_classification == RetryClassification.NOT_RETRYABLE


# ---------------------------------------------------------------------------
# Routing decision
# ---------------------------------------------------------------------------


class TestRoutingDecision:
    def test_decision_records_reasons(self):
        decision = RoutingDecision(
            request_id="req_1",
            selected_model_id="mdl_1",
            selected_provider_id="prv_1",
            selected_model_identifier="example-model-1",
            reason_codes=[
                RoutingReasonCode.CAPABILITY_MATCH,
                RoutingReasonCode.HEALTHY,
                RoutingReasonCode.POLICY_ALLOWED,
                RoutingReasonCode.WITHIN_COST_LIMIT,
            ],
            candidates_considered=["mdl_1", "mdl_2", "mdl_3"],
            rejected_candidates=[
                RejectedCandidate(
                    model_id="mdl_2",
                    provider_id="prv_2",
                    model_identifier="example-model-2",
                    reason_codes=[RoutingReasonCode.CAPABILITY_MISMATCH],
                ),
                RejectedCandidate(
                    model_id="mdl_3",
                    provider_id="prv_1",
                    model_identifier="example-model-3",
                    reason_codes=[RoutingReasonCode.EXCEEDS_COST_LIMIT],
                ),
            ],
            decided_at=datetime.now(timezone.utc),
            decision_latency_ms=12,
        )
        assert len(decision.rejected_candidates) == 2
        assert RoutingReasonCode.HEALTHY in decision.reason_codes

    def test_decision_is_frozen(self):
        d = RoutingDecision(
            request_id="r", selected_model_id="m", selected_provider_id="p",
            selected_model_identifier="x",
            reason_codes=[RoutingReasonCode.HEALTHY],
            candidates_considered=["m"],
            decided_at=datetime.now(timezone.utc),
            decision_latency_ms=0,
        )
        with pytest.raises(Exception):
            d.selected_model_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Credential reference (no secret material)
# ---------------------------------------------------------------------------


class TestCredentialReference:
    def test_reference_carries_no_secret(self):
        ref = CredentialReference(
            id="crd_1",
            organization_id="org_1",
            provider_id="prv_1",
            credential_type=CredentialType.BYOK,
            status=CredentialStatus.ACTIVE,
            label="my-openai-key",
            created_at=datetime.now(timezone.utc),
        )
        # Boundary assertion: the dumped dict must not contain any key that
        # looks like a secret.
        dumped = ref.model_dump()
        for key in dumped:
            assert "secret" not in key.lower()
            assert "api_key" not in key.lower()
            assert "token" not in key.lower()

    def test_reference_is_frozen(self):
        ref = CredentialReference(
            id="c", organization_id="o", provider_id="p",
            credential_type=CredentialType.MANAGED,
            status=CredentialStatus.ACTIVE,
            created_at=datetime.now(timezone.utc),
        )
        with pytest.raises(Exception):
            ref.status = CredentialStatus.REVOKED  # type: ignore[misc]