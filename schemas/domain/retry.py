"""
Retry and Fallback Policy Schemas (C2 §26-29).
"""

from __future__ import annotations

from pydantic import Field

from schemas.domain.base import DSRTSchema


class RetryPolicy(DSRTSchema):
    """Configurable retry behavior for model requests."""

    max_retries: int = Field(default=2, ge=0, le=10)
    initial_backoff_seconds: float = Field(default=1.0, ge=0.001, le=30.0)
    backoff_multiplier: float = Field(default=2.0, ge=1.0, le=5.0)
    max_backoff_seconds: float = Field(default=30.0, ge=1.0, le=120.0)

    # Whether to attempt a different model if all retries on the primary model fail.
    allow_fallback: bool = True

    # Maximum number of fallback model attempts after the primary model exhausts retries.
    max_fallback_attempts: int = Field(default=1, ge=0, le=5)