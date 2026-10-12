"""Unit tests for the Usage Meter and Cost Calculator (C2.10)."""

from decimal import Decimal

from core.models.usage.calculator import CostCalculator
from schemas.domain import Usage
from schemas.domain.provider import ModelPricing


class TestCostCalculator:
    def test_calculate_cost_standard(self):
        usage = Usage(input_tokens=1000000, output_tokens=2000000)
        pricing = ModelPricing(
            input_cost_per_m=Decimal("5.0"),
            output_cost_per_m=Decimal("15.0"),
        )
        
        cost = CostCalculator.calculate_estimated_cost(usage, pricing)
        # 1M * $5 + 2M * $15 = $35
        assert cost == Decimal("35.000000")

    def test_calculate_cost_fractional(self):
        usage = Usage(input_tokens=500, output_tokens=100)
        pricing = ModelPricing(
            input_cost_per_m=Decimal("2.50"),
            output_cost_per_m=Decimal("10.00"),
        )
        
        cost = CostCalculator.calculate_estimated_cost(usage, pricing)
        # (500 / 1M) * 2.50 = 0.00125
        # (100 / 1M) * 10.00 = 0.001
        # Total = 0.002250
        assert cost == Decimal("0.002250")

    def test_calculate_cost_missing_usage(self):
        usage = Usage(input_tokens=None, output_tokens=None)
        pricing = ModelPricing(
            input_cost_per_m=Decimal("2.50"),
            output_cost_per_m=Decimal("10.00"),
        )
        
        cost = CostCalculator.calculate_estimated_cost(usage, pricing)
        assert cost == Decimal("0.000000")