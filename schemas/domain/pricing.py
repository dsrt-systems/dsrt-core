"""
DSRT C10 Pricing Snapshots (D8 refinement).

A PricingSnapshot is IMMUTABLE. Once captured, it is never modified.
Every ExecutionTrace binds to the pricing snapshot that was current
at the moment of admission. If the provider later changes prices,
the historical execution still reports its original cost basis.

This is foundational for DSRT's cost-efficiency benchmarking — a
comparison from 2025-03 must remain reproducible in 2026-07.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field

from schemas.domain.base import DSRTImmutableSchema, DSRTSchema


class PricingSource(str, Enum):
    """Where a pricing snapshot came from."""
    PROVIDER_API = "PROVIDER_API"           # Pulled from provider's pricing endpoint
    PROVIDER_PUBLISHED = "PROVIDER_PUBLISHED"  # Scraped/documented from provider's price page
    MANUAL_ENTRY = "MANUAL_ENTRY"            # Human-entered
    CONTRACT_NEGOTIATED = "CONTRACT_NEGOTIATED"  # Enterprise contract rate
    DEFAULT_FALLBACK = "DEFAULT_FALLBACK"    # When no better data exists


class PricingUnit(str, Enum):
    PER_1K_TOKENS = "per_1k_tokens"
    PER_1M_TOKENS = "per_1m_tokens"
    PER_REQUEST = "per_request"
    PER_SECOND = "per_second"
    PER_MINUTE = "per_minute"


class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"
    INR = "INR"


class PricingSnapshot(DSRTImmutableSchema):
    """Immutable pricing record (D8).

    Fields required by D8:
      - provider, model_identifier
      - input_price, output_price, cached_input_price
      - currency, pricing_unit
      - source, effective_at, captured_at

    NEVER modified after creation.
    """
    id: str

    # Model identity
    provider_slug: str
    model_identifier: str
    model_id: str | None = None  # FK to models table if known
    provider_id: str | None = None

    # Pricing values
    input_price: float
    output_price: float
    cached_input_price: float | None = None  # Many providers offer caching discount
    reasoning_price: float | None = None     # For reasoning-model surcharges

    # Classification
    currency: Currency = Currency.USD
    pricing_unit: PricingUnit = PricingUnit.PER_1M_TOKENS

    # Provenance
    source: PricingSource
    source_url: str | None = None
    source_document_hash: str | None = None  # Hash of the source doc if any

    # Validity window
    effective_at: datetime       # When this price became effective (per provider)
    expires_at: datetime | None = None

    # Audit
    captured_at: datetime        # When DSRT recorded this snapshot
    captured_by: str | None = None  # User or system identifier

    # Content hash for dedup detection (do not treat as uniqueness constraint)
    content_hash: str

    # Free-form annotations (never used for pricing math)
    notes: str | None = None


class PricingSnapshotCreate(DSRTSchema):
    provider_slug: str
    model_identifier: str
    model_id: str | None = None
    provider_id: str | None = None
    input_price: float
    output_price: float
    cached_input_price: float | None = None
    reasoning_price: float | None = None
    currency: Currency = Currency.USD
    pricing_unit: PricingUnit = PricingUnit.PER_1M_TOKENS
    source: PricingSource
    source_url: str | None = None
    source_document_hash: str | None = None
    effective_at: datetime
    expires_at: datetime | None = None
    captured_by: str | None = None
    notes: str | None = None


class PricingLookupResult(DSRTSchema):
    """Returned when resolving pricing at execution admission."""
    snapshot: PricingSnapshot
    is_fresh: bool                 # effective_at within freshness window
    is_fallback: bool              # resolved via DEFAULT_FALLBACK
    age_seconds: int