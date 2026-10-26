"""
Pricing snapshots — versioned provider price tables.

Used to estimate cost when the provider does not return a dollar amount
(common for BYOK). Snapshots are immutable once created so historical
cost estimates remain interpretable after price changes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field


class ModelPrice(BaseModel):
    """Per-model token (and optional fixed) pricing."""

    provider: str
    model_id: str
    input_price_per_1k_usd: float
    output_price_per_1k_usd: float
    cached_input_price_per_1k_usd: float | None = None
    fixed_cost_per_call_usd: float = 0.0
    currency: str = "USD"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolPrice(BaseModel):
    """Optional per-tool unit pricing."""

    tool_name: str
    price_per_unit_usd: float
    unit_label: str = "call"
    metadata: dict[str, Any] = Field(default_factory=dict)


class PricingSnapshot(BaseModel):
    """
    Immutable pricing table at a point in time.

    All estimated costs reference a snapshot_id for auditability.
    """

    snapshot_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = "default"
    source: str = "manual"  # manual | provider_api | config
    model_prices: list[ModelPrice] = Field(default_factory=list)
    tool_prices: list[ToolPrice] = Field(default_factory=list)
    environment_price_per_minute_usd: float | None = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    def get_model_price(self, provider: str, model_id: str) -> ModelPrice | None:
        for p in self.model_prices:
            if p.provider == provider and p.model_id == model_id:
                return p
        return None

    def get_tool_price(self, tool_name: str) -> ToolPrice | None:
        for p in self.tool_prices:
            if p.tool_name == tool_name:
                return p
        return None


class PricingStore(Protocol):
    async def get(self, snapshot_id: str) -> PricingSnapshot | None: ...
    async def latest(self, name: str = "default") -> PricingSnapshot | None: ...
    async def save(self, snapshot: PricingSnapshot) -> PricingSnapshot: ...


class InMemoryPricingStore:
    """Default store for tests and local development."""

    def __init__(self) -> None:
        self._by_id: dict[str, PricingSnapshot] = {}
        self._by_name: dict[str, list[str]] = {}

    async def get(self, snapshot_id: str) -> PricingSnapshot | None:
        return self._by_id.get(snapshot_id)

    async def latest(self, name: str = "default") -> PricingSnapshot | None:
        ids = self._by_name.get(name) or []
        if not ids:
            return None
        return self._by_id.get(ids[-1])

    async def save(self, snapshot: PricingSnapshot) -> PricingSnapshot:
        self._by_id[snapshot.snapshot_id] = snapshot
        self._by_name.setdefault(snapshot.name, []).append(snapshot.snapshot_id)
        return snapshot


class PricingDirectory:
    """
    Resolves prices and estimates dollar amounts from usage.
    """

    def __init__(self, store: PricingStore | None = None) -> None:
        self._store = store or InMemoryPricingStore()

    async def register(self, snapshot: PricingSnapshot) -> PricingSnapshot:
        return await self._store.save(snapshot)

    async def get(self, snapshot_id: str) -> PricingSnapshot | None:
        return await self._store.get(snapshot_id)

    async def latest(self, name: str = "default") -> PricingSnapshot | None:
        return await self._store.latest(name)

    def estimate_model_cost(
        self,
        *,
        snapshot: PricingSnapshot,
        provider: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
    ) -> tuple[float | None, str | None]:
        """
        Returns (amount_usd, error_reason).
        amount_usd is None when price is unknown.
        """
        price = snapshot.get_model_price(provider, model_id)
        if price is None:
            return None, f"No price for {provider}/{model_id} in snapshot {snapshot.snapshot_id}"

        cached_rate = (
            price.cached_input_price_per_1k_usd
            if price.cached_input_price_per_1k_usd is not None
            else price.input_price_per_1k_usd
        )
        billable_input = max(0, input_tokens - cached_tokens)
        amount = (
            (billable_input / 1000.0) * price.input_price_per_1k_usd
            + (cached_tokens / 1000.0) * cached_rate
            + (output_tokens / 1000.0) * price.output_price_per_1k_usd
            + price.fixed_cost_per_call_usd
        )
        return amount, None

    def estimate_tool_cost(
        self,
        *,
        snapshot: PricingSnapshot,
        tool_name: str,
        quantity: float = 1.0,
    ) -> tuple[float | None, str | None]:
        price = snapshot.get_tool_price(tool_name)
        if price is None:
            return None, f"No tool price for '{tool_name}' in snapshot {snapshot.snapshot_id}"
        return price.price_per_unit_usd * quantity, None

    def estimate_environment_cost(
        self,
        *,
        snapshot: PricingSnapshot,
        duration_minutes: float,
    ) -> tuple[float | None, str | None]:
        rate = snapshot.environment_price_per_minute_usd
        if rate is None:
            return None, "No environment pricing in snapshot"
        return rate * duration_minutes, None