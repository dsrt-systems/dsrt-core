"""
Cost Calculator (C2 §36).

Deterministically calculates estimated costs based on token usage and model pricing.
Enforces the strict separation between estimated cost and provider-reported cost.
"""

from __future__ import annotations

from decimal import Decimal

from schemas.domain.model_fabric import Usage
from schemas.domain.provider import ModelPricing


class CostCalculator:
    """Calculates USD cost estimates from token counts."""

    # Standard industry pricing denominator
    _PRICE_PER_UNIT = Decimal("1000000")

    @classmethod
    def calculate_estimated_cost(
        cls, usage: Usage, pricing: ModelPricing
    ) -> Decimal:
        """
        Calculate the estimated cost based on DSRT's observed token counts
        and the model's configured pricing per 1M tokens.
        """
        total_cost = Decimal("0.0")

        if usage.input_tokens and pricing.input_cost_per_m:
            total_cost += (Decimal(usage.input_tokens) / cls._PRICE_PER_UNIT) * pricing.input_cost_per_m

        if usage.output_tokens and pricing.output_cost_per_m:
            total_cost += (Decimal(usage.output_tokens) / cls._PRICE_PER_UNIT) * pricing.output_cost_per_m

        if usage.cached_tokens and pricing.cached_input_cost_per_m:
            total_cost += (Decimal(usage.cached_tokens) / cls._PRICE_PER_UNIT) * pricing.cached_input_cost_per_m
            
        if usage.reasoning_tokens and pricing.reasoning_cost_per_m:
            total_cost += (Decimal(usage.reasoning_tokens) / cls._PRICE_PER_UNIT) * pricing.reasoning_cost_per_m

        # Quantize to 6 decimal places for precision without floating point noise
        return total_cost.quantize(Decimal("0.000001"))