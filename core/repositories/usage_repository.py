"""
Usage Repository.

Data access layer for UsageRecords.
"""

from __future__ import annotations

from decimal import Decimal
from sqlalchemy import func, select

from core.repositories.base import Repository
from core.storage.models import UsageRecord


class UsageRepository(Repository):
    
    async def record_usage(
        self,
        *,
        organization_id: str,
        execution_id: str,
        resource_type: str,
        provider_slug: str | None,
        model_identifier: str | None,
        input_tokens: int | None,
        output_tokens: int | None,
        total_tokens: int | None,
        estimated_cost_usd: Decimal | None,
        provider_reported_cost_usd: Decimal | None,
        latency_ms: int | None,
        metadata: dict | None = None,
    ) -> UsageRecord:
        """Persist a single usage record."""
        record = UsageRecord(
            organization_id=organization_id,
            execution_id=execution_id,
            resource_type=resource_type,
            provider_slug=provider_slug,
            model_identifier=model_identifier,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost_usd,
            provider_reported_cost_usd=provider_reported_cost_usd,
            latency_ms=latency_ms,
            usage_metadata=metadata or {},
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_execution_aggregate(self, execution_id: str) -> dict[str, Any]:
        """Aggregate all token usage and costs for a specific execution."""
        stmt = (
            select(
                func.sum(UsageRecord.input_tokens).label("input"),
                func.sum(UsageRecord.output_tokens).label("output"),
                func.sum(UsageRecord.total_tokens).label("total"),
                func.sum(UsageRecord.estimated_cost_usd).label("est_cost"),
                func.sum(UsageRecord.provider_reported_cost_usd).label("prov_cost"),
            )
            .where(UsageRecord.execution_id == execution_id)
        )
        
        result = await self._session.execute(stmt)
        row = result.fetchone()

        if not row:
            return {
                "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                "estimated_cost_usd": Decimal("0.0"),
                "provider_reported_cost_usd": Decimal("0.0")
            }

        return {
            "input_tokens": row.input or 0,
            "output_tokens": row.output or 0,
            "total_tokens": row.total or 0,
            "estimated_cost_usd": row.est_cost or Decimal("0.0"),
            "provider_reported_cost_usd": row.prov_cost or Decimal("0.0"),
        }