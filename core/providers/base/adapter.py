"""
Model Provider Adapter Protocol (C2 §8, C4 §13).

Every provider (OpenAI, Anthropic, Gemini, Local, BYOK) implements this interface.
Translates DSRT's canonical requests into provider-specific API calls.

C4.5 adds the `embed()` method for embedding generation — the same adapter
that handles reasoning also handles embeddings, keeping the BYOK credential
system unified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol

from schemas.domain import (
    ModelRequest,
    ModelResponse,
    ProviderHealth,
    StreamEvent,
    TokenCountRequest,
    TokenCountResponse,
)


@dataclass(frozen=True)
class EmbeddingRequest:
    """Canonical embedding request — provider-neutral."""

    texts: list[str]
    model_identifier: str
    dimensions: int | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class EmbeddingResponse:
    """Canonical embedding response — provider-neutral."""

    embeddings: list[list[float]]
    model_identifier: str
    dimensions: int
    total_tokens: int = 0
    metadata: dict = field(default_factory=dict)


class ModelProviderAdapter(Protocol):
    """The canonical DSRT Provider Adapter Interface."""

    async def generate(
        self, request: ModelRequest, api_key: str | None = None,
    ) -> ModelResponse:
        """Execute a blocking model generation request."""
        ...

    async def stream(
        self, request: ModelRequest, api_key: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Execute a streaming model generation request."""
        ...

    async def count_tokens(
        self, request: TokenCountRequest, model_identifier: str,
    ) -> TokenCountResponse:
        """Count tokens locally or via provider API."""
        ...

    async def embed(
        self, request: EmbeddingRequest, api_key: str | None = None,
    ) -> EmbeddingResponse:
        """Generate embeddings for one or more texts (C4 §13)."""
        ...

    async def check_health(self) -> ProviderHealth:
        """Check provider operational health."""
        ...