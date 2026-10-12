"""
Usage Meter Service (C2 §11, §35).

Intercepts model responses, looks up dynamic pricing, calculates costs, 
and logs the usage into the durable database.
"""

from __future__ import annotations

from core.models.registry.registry import ModelRegistry
from core.models.usage.calculator import CostCalculator
from core.observability.logging import get_logger
from core.repositories.usage_repository import UsageRepository
from schemas.domain import ModelResponse, UsageRecord


logger = get_logger("dsrt.models.usage.meter")


class UsageMeter:
    """Meters usage and records accounting metrics."""

    def __init__(
        self,
        usage_repo: UsageRepository,
        model_registry: ModelRegistry,
    ) -> None:
        self._usage_repo = usage_repo
        self._model_registry = model_registry

    async def record_model_response(
        self,
        organization_id: str,
        execution_id: str,
        response: ModelResponse,
    ) -> UsageRecord:
        """Process a ModelResponse and store its usage record."""
        # 1. Fetch Model Pricing
        model = await self._model_registry.get_model(response.model_id)
        
        # 2. Calculate Estimated Cost
        estimated_cost = CostCalculator.calculate_estimated_cost(
            response.usage, model.pricing_config
        )

        # 3. Create persistent record
        record_orm = await self._usage_repo.record_usage(
            organization_id=organization_id,
            execution_id=execution_id,
            resource_type="model_call",
            provider_slug=model.provider_id,  # Will join logically
            model_identifier=response.model_identifier,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=response.usage.total_tokens,
            estimated_cost_usd=estimated_cost,
            provider_reported_cost_usd=response.usage.provider_reported_cost_usd,
            latency_ms=response.latency_ms,
            metadata={
                "request_id": response.request_id,
                "finish_reason": response.finish_reason.value,
            },
        )

        logger.info(
            "model_usage_recorded",
            execution_id=execution_id,
            request_id=response.request_id,
            model_identifier=response.model_identifier,
            total_tokens=response.usage.total_tokens,
            estimated_cost=str(estimated_cost),
        )

        return UsageRecord.model_validate(record_orm, from_attributes=True)
        
    async def get_execution_usage(self, execution_id: str) -> dict:
        """Fetch aggregated usage for an execution."""
        return await self._usage_repo.get_execution_aggregate(execution_id)