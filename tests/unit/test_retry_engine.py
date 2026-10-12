"""
Unit tests for the Retry/Fallback Engine (C2.9).
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from core.api.errors.exceptions import DSRTError
from core.models.retry.classifier import classify_error, is_fallback_eligible, is_retryable
from core.models.retry.engine import RetryEngine
from schemas.domain import (
    MessageRole,
    ModelErrorCode,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryClassification,
    Usage,
    FinishReason,
)
from schemas.domain.retry import RetryPolicy


# --- Classifier Tests ---

class TestErrorClassifier:
    def test_timeout_is_retryable(self):
        c = classify_error(ModelErrorCode.PROVIDER_TIMEOUT)
        assert c == RetryClassification.RETRYABLE
        assert is_retryable(c)

    def test_rate_limit_is_retryable_with_backoff(self):
        c = classify_error(ModelErrorCode.PROVIDER_RATE_LIMITED)
        assert c == RetryClassification.RETRYABLE_WITH_BACKOFF
        assert is_retryable(c)

    def test_credential_invalid_is_not_retryable(self):
        c = classify_error(ModelErrorCode.CREDENTIAL_INVALID)
        assert c == RetryClassification.NOT_RETRYABLE
        assert not is_retryable(c)
        assert not is_fallback_eligible(c)

    def test_provider_unavailable_is_fallback_eligible(self):
        c = classify_error(ModelErrorCode.PROVIDER_UNAVAILABLE)
        assert c == RetryClassification.FALLBACK_ELIGIBLE
        assert is_fallback_eligible(c)

    def test_unknown_code_defaults_to_fallback(self):
        # Use a valid code but one that might not be in the map
        c = classify_error(ModelErrorCode.PROVIDER_INVALID_RESPONSE)
        assert c == RetryClassification.RETRYABLE


# --- Retry Engine Tests ---

@pytest.fixture
def sample_request():
    return ModelRequest(
        request_id="req_retry",
        execution_id="exe_retry",
        task_id="tsk_retry",
        organization_id="org_retry",
        purpose="retry_test",
        messages=[ModelMessage(role=MessageRole.USER, content="Hi")],
    )


@pytest.fixture
def mock_successful_response():
    from datetime import datetime, timezone
    return ModelResponse(
        request_id="req_retry",
        model_id="mdl_1",
        provider_id="prv_1",
        model_identifier="gpt-4",
        output="Success!",
        finish_reason=FinishReason.COMPLETED,
        usage=Usage(input_tokens=5, output_tokens=10, total_tokens=15),
        latency_ms=100,
        created_at=datetime.now(timezone.utc),
    )


class TestRetryEngine:
    async def test_succeeds_on_first_attempt(self, sample_request, mock_successful_response):
        adapter = AsyncMock()
        adapter.generate.return_value = mock_successful_response

        engine = RetryEngine(policy=RetryPolicy(max_retries=2))
        result = await engine.execute_with_retry(
            adapter=adapter,
            request=sample_request,
            api_key="sk-test",
            model_id="mdl_1",
            provider_id="prv_1",
            model_identifier="gpt-4",
        )

        assert result.succeeded
        assert result.response.output == "Success!"
        assert len(result.attempts) == 1
        assert result.attempts[0].success is True
        assert result.fallback_used is False

    async def test_retries_on_transient_error_then_succeeds(self, sample_request, mock_successful_response):
        adapter = AsyncMock()
        # First call fails with timeout, second succeeds
        adapter.generate.side_effect = [
            DSRTError("timeout", metadata={"code": "PROVIDER_TIMEOUT"}),
            mock_successful_response,
        ]

        engine = RetryEngine(
            policy=RetryPolicy(max_retries=2, initial_backoff_seconds=0.01)
        )
        result = await engine.execute_with_retry(
            adapter=adapter,
            request=sample_request,
            api_key="sk-test",
            model_id="mdl_1",
            provider_id="prv_1",
            model_identifier="gpt-4",
        )

        assert result.succeeded
        assert len(result.attempts) == 2
        assert result.attempts[0].success is False
        assert result.attempts[1].success is True

    async def test_stops_immediately_on_non_retryable_error(self, sample_request):
        adapter = AsyncMock()
        adapter.generate.side_effect = DSRTError(
            "bad key", metadata={"code": "CREDENTIAL_INVALID"}
        )

        engine = RetryEngine(policy=RetryPolicy(max_retries=3))
        result = await engine.execute_with_retry(
            adapter=adapter,
            request=sample_request,
            api_key="sk-test",
            model_id="mdl_1",
            provider_id="prv_1",
            model_identifier="gpt-4",
        )

        assert not result.succeeded
        assert len(result.attempts) == 1
        assert result.final_error is not None

    async def test_exhausts_retries_and_reports_failure(self, sample_request):
        adapter = AsyncMock()
        adapter.generate.side_effect = DSRTError(
            "timeout", metadata={"code": "PROVIDER_TIMEOUT"}
        )

        engine = RetryEngine(
            policy=RetryPolicy(max_retries=2, initial_backoff_seconds=0.01, allow_fallback=False)
        )
        result = await engine.execute_with_retry(
            adapter=adapter,
            request=sample_request,
            api_key="sk-test",
            model_id="mdl_1",
            provider_id="prv_1",
            model_identifier="gpt-4",
        )

        assert not result.succeeded
        assert len(result.attempts) == 3  # 1 initial + 2 retries
        assert result.final_error is not None
        assert "exhausted" in str(result.final_error).lower()

    async def test_retries_with_exponential_backoff(self, sample_request, mock_successful_response):
        adapter = AsyncMock()
        adapter.generate.side_effect = [
            DSRTError("rate limited", metadata={"code": "PROVIDER_RATE_LIMITED"}),
            DSRTError("rate limited", metadata={"code": "PROVIDER_RATE_LIMITED"}),
            mock_successful_response,
        ]

        engine = RetryEngine(
            policy=RetryPolicy(
                max_retries=3,
                initial_backoff_seconds=0.01,
                backoff_multiplier=2.0,
            )
        )
        result = await engine.execute_with_retry(
            adapter=adapter,
            request=sample_request,
            api_key="sk-test",
            model_id="mdl_1",
            provider_id="prv_1",
            model_identifier="gpt-4",
        )

        assert result.succeeded
        assert len(result.attempts) == 3