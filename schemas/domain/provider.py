"""
Provider and Model schemas (C2 §6, §7).

These schemas represent the authoritative registry of intelligence available
to DSRT. Models are characterized by their capabilities, not their marketing names.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import Field

from schemas.domain.base import DSRTSchema, TimestampedSchema
from schemas.domain.enums import ProviderStatus, ProviderType


# =============================================================================
# Sub-Schemas (Capabilities, Pricing, Context)
# =============================================================================


class ModelCapabilityProfile(DSRTSchema):
    """Machine-readable model capabilities (C2 §15)."""

    text_generation: bool = True
    structured_output: bool = False
    tool_calling: bool = False
    vision: bool = False
    audio: bool = False
    video: bool = False
    reasoning: bool = False
    streaming: bool = True
    system_instructions: bool = True


class ModelContextConfig(DSRTSchema):
    """Context window and limits (C2 §6)."""

    max_input_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    max_tool_results: int | None = None
    supports_context_caching: bool = False


class ModelPricing(DSRTSchema):
    """Pricing configuration for cost estimation (C2 §6, §36).
    Values represent cost in USD per 1,000,000 tokens.
    """

    input_cost_per_m: Decimal = Field(default=Decimal(0), ge=0)
    output_cost_per_m: Decimal = Field(default=Decimal(0), ge=0)
    cached_input_cost_per_m: Decimal | None = Field(default=None, ge=0)
    reasoning_cost_per_m: Decimal | None = Field(default=None, ge=0)


# =============================================================================
# Core Domain Schemas (Registration & Output)
# =============================================================================


class ProviderCreate(DSRTSchema):
    slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    provider_type: ProviderType
    configuration: dict[str, Any] = Field(default_factory=dict)


class Provider(TimestampedSchema):
    id: str
    slug: str
    name: str
    description: str
    provider_type: ProviderType
    status: ProviderStatus
    configuration: dict[str, Any]


class ModelCreate(DSRTSchema):
    provider_id: str
    slug: str = Field(min_length=1, max_length=200, pattern=r"^[a-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=200)
    model_identifier: str = Field(min_length=1, max_length=200)
    version: str
    
    # Nested configurations
    capabilities: ModelCapabilityProfile
    context_config: ModelContextConfig
    pricing_config: ModelPricing = Field(default_factory=ModelPricing)
    
    metadata: dict[str, Any] = Field(default_factory=dict)


class Model(TimestampedSchema):
    id: str
    provider_id: str
    slug: str
    name: str
    model_identifier: str
    version: str
    status: str
    
    capabilities: ModelCapabilityProfile
    context_config: ModelContextConfig
    pricing_config: ModelPricing
    
    metadata: dict[str, Any] = Field(
        default_factory=dict, 
        # Using alias because ORM uses 'capabilities' as a JSON blob containing everything in C1
        # In C2, we parse it out gracefully.
    )

    # Note: To avoid complex ORM migrations right now, the ORM's JSONB `capabilities` 
    # column will store the combined dict of capabilities, context, and pricing.
    # The ModelRegistry service will handle packing/unpacking this JSON blob.