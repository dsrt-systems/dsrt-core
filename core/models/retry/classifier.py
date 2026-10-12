"""
Error Classifier (C2 §27).

Maps raw provider exceptions and DSRT ModelError codes into retry classifications.
"""

from __future__ import annotations

from schemas.domain.enums import ModelErrorCode, RetryClassification


# Static classification map based on the C2 §27 error taxonomy
_CLASSIFICATION_MAP: dict[ModelErrorCode, RetryClassification] = {
    # Retryable (transient)
    ModelErrorCode.PROVIDER_TIMEOUT: RetryClassification.RETRYABLE,
    ModelErrorCode.PROVIDER_OVERLOADED: RetryClassification.RETRYABLE,
    ModelErrorCode.PROVIDER_INTERNAL_ERROR: RetryClassification.RETRYABLE,

    # Retryable with backoff (rate limits)
    ModelErrorCode.PROVIDER_RATE_LIMITED: RetryClassification.RETRYABLE_WITH_BACKOFF,

    # Non-retryable (permanent errors on this provider)
    ModelErrorCode.CREDENTIAL_INVALID: RetryClassification.NOT_RETRYABLE,
    ModelErrorCode.CREDENTIAL_REVOKED: RetryClassification.NOT_RETRYABLE,
    ModelErrorCode.CREDENTIAL_MISSING: RetryClassification.NOT_RETRYABLE,
    ModelErrorCode.REQUEST_INVALID: RetryClassification.NOT_RETRYABLE,
    ModelErrorCode.MODEL_CAPABILITY_UNSUPPORTED: RetryClassification.NOT_RETRYABLE,
    ModelErrorCode.POLICY_DENIED: RetryClassification.NOT_RETRYABLE,
    ModelErrorCode.CONTENT_FILTERED: RetryClassification.NOT_RETRYABLE,
    ModelErrorCode.REQUEST_CANCELLED: RetryClassification.NOT_RETRYABLE,

    # Fallback-eligible (try a different model/provider)
    ModelErrorCode.PROVIDER_UNAVAILABLE: RetryClassification.FALLBACK_ELIGIBLE,
    ModelErrorCode.MODEL_UNAVAILABLE: RetryClassification.FALLBACK_ELIGIBLE,
    ModelErrorCode.MODEL_NOT_FOUND: RetryClassification.FALLBACK_ELIGIBLE,
    ModelErrorCode.QUOTA_EXCEEDED: RetryClassification.FALLBACK_ELIGIBLE,

    # Context/schema errors (non-retryable on the same request, but may be fixable)
    ModelErrorCode.CONTEXT_TOO_LARGE: RetryClassification.NOT_RETRYABLE,
    ModelErrorCode.REQUEST_TOO_LARGE: RetryClassification.NOT_RETRYABLE,
    ModelErrorCode.RESPONSE_SCHEMA_INVALID: RetryClassification.RETRYABLE,
    ModelErrorCode.PROVIDER_INVALID_RESPONSE: RetryClassification.RETRYABLE,
}


def classify_error(code: ModelErrorCode) -> RetryClassification:
    """Classify a ModelErrorCode into a retry action."""
    return _CLASSIFICATION_MAP.get(code, RetryClassification.FALLBACK_ELIGIBLE)


def is_retryable(classification: RetryClassification) -> bool:
    """Whether this classification should trigger a retry on the same model."""
    return classification in (
        RetryClassification.RETRYABLE,
        RetryClassification.RETRYABLE_WITH_BACKOFF,
    )


def is_fallback_eligible(classification: RetryClassification) -> bool:
    """Whether this classification should trigger a fallback to another model."""
    return classification == RetryClassification.FALLBACK_ELIGIBLE