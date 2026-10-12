"""
Usage record schemas.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import AliasChoices, Field

from schemas.domain.base import DSRTSchema, TimestampedSchema


class UsageRecordCreate(DSRTSchema):
    resource_type: str = Field(min_length=1, max_length=50)
    provider_slug: str | None = None
    model_identifier: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_usd: Decimal | None = Field(default=None, ge=0)
    provider_reported_cost_usd: Decimal | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    metadata: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("usage_metadata", "metadata"),
    )


class UsageRecord(TimestampedSchema):
    id: str
    organization_id: str
    execution_id: str
    resource_type: str
    provider_slug: str | None
    model_identifier: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    estimated_cost_usd: Decimal | None
    provider_reported_cost_usd: Decimal | None
    latency_ms: int | None
    metadata: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("usage_metadata", "metadata"),
    )