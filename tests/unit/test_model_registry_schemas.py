"""Unit tests for Provider and Model Pydantic validation."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from schemas.domain.enums import ProviderType
from schemas.domain.provider import (
    ModelCapabilityProfile,
    ModelContextConfig,
    ModelCreate,
    ModelPricing,
    ProviderCreate,
)


def test_provider_create_valid():
    p = ProviderCreate(
        slug="openai",
        name="OpenAI",
        provider_type=ProviderType.CLOUD,
    )
    assert p.slug == "openai"


def test_model_create_valid():
    m = ModelCreate(
        provider_id="prv_1",
        slug="gpt-4o",
        name="GPT-4o",
        model_identifier="gpt-4o-2024-08-06",
        version="2024-08-06",
        capabilities=ModelCapabilityProfile(
            text_generation=True,
            tool_calling=True,
            vision=True,
        ),
        context_config=ModelContextConfig(
            max_input_tokens=128000,
            max_output_tokens=16384,
        ),
        pricing_config=ModelPricing(
            input_cost_per_m=Decimal("5.0"),
            output_cost_per_m=Decimal("15.0"),
        )
    )
    assert m.capabilities.vision is True
    assert m.context_config.max_input_tokens == 128000
    assert m.pricing_config.input_cost_per_m == Decimal("5.0")


def test_model_create_rejects_negative_context():
    with pytest.raises(ValidationError):
        ModelContextConfig(max_input_tokens=-100, max_output_tokens=100)


def test_model_create_rejects_negative_pricing():
    with pytest.raises(ValidationError):
        ModelPricing(input_cost_per_m=Decimal("-1.0"))