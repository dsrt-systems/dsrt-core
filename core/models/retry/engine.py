"""
Retry Engine (C2 §26-29).

The core retry/fallback loop for model generation requests.

Flow:
    1. Attempt generation on the selected model.
    2. On failure, classify the error.
    3. If RETRYABLE or RETRYABLE_WITH_BACKOFF → retry (up to max_retries).
    4. If FALLBACK_ELIGIBLE and allow_fallback → resolve fallback model → retry on fallback.
    5. If NOT_RETRYABLE → raise immediately.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from core.api.errors.exceptions import DSRTError
from core.models.fallback.resolver import FallbackResolver
from core.models.retry.classifier import classify_error, is_fallback_eligible, is_retryable
from core.observability.logging import get_logger
from core.providers.base.adapter import ModelProviderAdapter
from schemas.domain import (
    ModelError,
    ModelErrorCode,
    ModelRequest,
    ModelResponse,
    RetryClassification,
)
from schemas.domain.retry import RetryPolicy


logger = get_logger("dsrt.models.retry")


@dataclass
class RetryAttempt:
    """Record of one attempt."""
    attempt_number: int
    model_id: str
    provider_id: str
    model_identifier: str
    success: bool
    error: ModelError | None = None
    latency_ms: int = 0


@dataclass
class RetryResult:
    """The final outcome of the retry engine."""
    response: ModelResponse | None = None
    attempts: list[RetryAttempt] = field(default_factory=list)
    fallback_used: bool = False
    final_error: DSRTError | None = None

    @property
    def succeeded(self) -> bool:
        return self.response is not None


class RetryEngine:
    """Production retry/fallback engine for model generation."""

    def __init__(
        self,
        fallback_resolver: FallbackResolver | None = None,
        policy: RetryPolicy | None = None,
    ) -> None:
        self._fallback = fallback_resolver
        self._policy = policy or RetryPolicy()

    async def execute_with_retry(
        self,
        adapter: ModelProviderAdapter,
        request: ModelRequest,
        api_key: str | None,
        model_id: str,
        provider_id: str,
        model_identifier: str,
    ) -> RetryResult:
        """Execute a model request with automatic retry and fallback."""
        result = RetryResult()
        policy = self._policy

        # --- Phase 1: Primary model retries ---
        for attempt_num in range(1, policy.max_retries + 2):  # +2 because range is exclusive and attempt 1 is the initial try
            start = time.perf_counter()

            try:
                # Tag the request with attempt number
                request.attempt = attempt_num

                response = await adapter.generate(request, api_key=api_key)

                latency = int((time.perf_counter() - start) * 1000)
                result.attempts.append(
                    RetryAttempt(
                        attempt_number=attempt_num,
                        model_id=model_id,
                        provider_id=provider_id,
                        model_identifier=model_identifier,
                        success=True,
                        latency_ms=latency,
                    )
                )
                result.response = response
                return result

            except DSRTError as e:
                latency = int((time.perf_counter() - start) * 1000)
                error_meta = e.metadata or {}
                error_code_str = error_meta.get("code", "PROVIDER_INTERNAL_ERROR")

                try:
                    error_code = ModelErrorCode(error_code_str)
                except ValueError:
                    error_code = ModelErrorCode.PROVIDER_INTERNAL_ERROR

                classification = classify_error(error_code)

                model_error = ModelError(
                    code=error_code,
                    message=str(e),
                    retry_classification=classification,
                    provider_id=provider_id,
                    model_id=model_id,
                    request_id=request.request_id,
                    attempt=attempt_num,
                )

                result.attempts.append(
                    RetryAttempt(
                        attempt_number=attempt_num,
                        model_id=model_id,
                        provider_id=provider_id,
                        model_identifier=model_identifier,
                        success=False,
                        error=model_error,
                        latency_ms=latency,
                    )
                )

                logger.warning(
                    "model_request_failed",
                    request_id=request.request_id,
                    attempt=attempt_num,
                    error_code=error_code.value,
                    classification=classification.value,
                )

                # Decision: retry, fallback, or raise
                if classification == RetryClassification.NOT_RETRYABLE:
                    result.final_error = e
                    return result

                if is_retryable(classification) and attempt_num <= policy.max_retries:
                    backoff = min(
                        policy.initial_backoff_seconds * (policy.backoff_multiplier ** (attempt_num - 1)),
                        policy.max_backoff_seconds,
                    )
                    logger.info(
                        "model_request_retry",
                        request_id=request.request_id,
                        attempt=attempt_num,
                        backoff_seconds=backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue

                # Exhausted retries on primary model
                break

            except Exception as e:
                latency = int((time.perf_counter() - start) * 1000)
                result.attempts.append(
                    RetryAttempt(
                        attempt_number=attempt_num,
                        model_id=model_id,
                        provider_id=provider_id,
                        model_identifier=model_identifier,
                        success=False,
                        error=ModelError(
                            code=ModelErrorCode.PROVIDER_INTERNAL_ERROR,
                            message=str(e),
                            retry_classification=RetryClassification.FALLBACK_ELIGIBLE,
                            request_id=request.request_id,
                            attempt=attempt_num,
                        ),
                        latency_ms=latency,
                    )
                )
                break

        # --- Phase 2: Fallback ---
        if policy.allow_fallback and self._fallback and policy.max_fallback_attempts > 0:
            logger.info(
                "fallback_initiated",
                request_id=request.request_id,
                failed_model=model_id,
            )

            for fb_attempt in range(policy.max_fallback_attempts):
                fallback_selection = await self._fallback.resolve_fallback(
                    request=request,
                    failed_model_id=model_id,
                    failed_provider_id=provider_id,
                )

                if not fallback_selection:
                    logger.warning("no_fallback_candidates", request_id=request.request_id)
                    break

                fb_model = fallback_selection.selected_model
                fb_provider = fallback_selection.selected_provider
                fb_adapter = adapter  # In production, the gateway resolves the correct adapter

                start = time.perf_counter()
                try:
                    request.attempt = len(result.attempts) + 1
                    setattr(request, "_selected_model_identifier", fb_model.model_identifier)

                    response = await fb_adapter.generate(request, api_key=api_key)

                    latency = int((time.perf_counter() - start) * 1000)
                    result.attempts.append(
                        RetryAttempt(
                            attempt_number=len(result.attempts) + 1,
                            model_id=fb_model.id,
                            provider_id=fb_provider.id,
                            model_identifier=fb_model.model_identifier,
                            success=True,
                            latency_ms=latency,
                        )
                    )
                    result.response = response
                    result.fallback_used = True
                    return result

                except Exception as fb_error:
                    latency = int((time.perf_counter() - start) * 1000)
                    result.attempts.append(
                        RetryAttempt(
                            attempt_number=len(result.attempts) + 1,
                            model_id=fb_model.id,
                            provider_id=fb_provider.id,
                            model_identifier=fb_model.model_identifier,
                            success=False,
                            error=ModelError(
                                code=ModelErrorCode.PROVIDER_INTERNAL_ERROR,
                                message=str(fb_error),
                                retry_classification=RetryClassification.FALLBACK_ELIGIBLE,
                                request_id=request.request_id,
                            ),
                            latency_ms=latency,
                        )
                    )
                    model_id = fb_model.id
                    provider_id = fb_provider.id
                    continue

        # All attempts exhausted
        if not result.final_error and result.attempts:
            last_error = result.attempts[-1].error
            result.final_error = DSRTError(
                f"All retry and fallback attempts exhausted ({len(result.attempts)} attempts).",
                metadata=last_error.model_dump() if last_error else {},
            )

        return result