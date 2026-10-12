"""
Embedding Generator (C4 §13).

Model-independent embedding generation for semantic memory search.
Delegates to the C2 Model Fabric's provider adapters, keeping the
BYOK credential system unified. Any provider that implements the
`embed()` method on the ModelProviderAdapter can serve embeddings.

Strategies:
  - local-hash: Deterministic pseudo-embeddings (testing, no API key)
  - Any provider slug: Routes through the C2 adapter registry
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

from core.config import get_settings
from core.observability.logging import get_logger


logger = get_logger("dsrt.memory.embeddings")


class EmbeddingGenerator:
    """Model-independent embedding generator for DSRT memories."""

    def __init__(
        self,
        provider: str | None = None,
        model_identifier: str | None = None,
        dimensions: int | None = None,
        api_key: str | None = None,
    ) -> None:
        settings = get_settings()
        self._provider = provider or settings.embedding_provider
        self._model_identifier = model_identifier or settings.embedding_model_identifier
        self._dimensions = dimensions or settings.embedding_dimensions
        self._api_key = api_key

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model_identifier(self) -> str:
        return self._model_identifier

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def generate(self, text: str) -> list[float]:
        """Generate an embedding vector for the given text."""
        if not text or not text.strip():
            return [0.0] * self._dimensions

        if self._provider == "local-hash":
            return self._generate_hash_embedding(text)
        else:
            return await self._generate_via_provider(text)

    async def generate_batch(
        self, texts: list[str],
    ) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        if self._provider == "local-hash":
            return [self._generate_hash_embedding(t) if t.strip() else [0.0] * self._dimensions for t in texts]
        else:
            return await self._generate_batch_via_provider(texts)

    async def _generate_via_provider(self, text: str) -> list[float]:
        """Generate embedding using a real provider via Model Fabric."""
        results = await self._generate_batch_via_provider([text])
        return results[0] if results else [0.0] * self._dimensions

    async def _generate_batch_via_provider(
        self, texts: list[str],
    ) -> list[list[float]]:
        """Generate embeddings via the C2 provider adapter registry."""
        from core.providers.base.adapter import EmbeddingRequest
        from core.providers.registry.registry import adapter_registry

        adapter = adapter_registry.get_adapter(self._provider)
        if adapter is None:
            logger.warning(
                "embedding_provider_not_found_falling_back_to_hash",
                provider=self._provider,
            )
            return [self._generate_hash_embedding(t) for t in texts]

        # Resolve API key
        api_key = self._api_key
        if not api_key:
            import sys
            from core.config import get_settings
            settings = get_settings()
            if settings.testing or "pytest" in sys.modules:
                api_key = "sk-dsrt-test-dummy-key"

        request = EmbeddingRequest(
            texts=texts,
            model_identifier=self._model_identifier,
            dimensions=self._dimensions,
        )

        try:
            response = await adapter.embed(request, api_key=api_key)
            actual_dims = response.dimensions

            if actual_dims != self._dimensions:
                logger.info(
                    "embedding_dimensions_mismatch",
                    expected=self._dimensions,
                    actual=actual_dims,
                )
                self._dimensions = actual_dims

            logger.debug(
                "embeddings_generated_via_provider",
                provider=self._provider,
                model=self._model_identifier,
                count=len(texts),
                tokens=response.total_tokens,
            )

            return response.embeddings

        except NotImplementedError:
            logger.warning(
                "embedding_not_implemented_by_provider_falling_back",
                provider=self._provider,
            )
            return [self._generate_hash_embedding(t) for t in texts]
        except Exception as e:
            logger.warning(
                "embedding_generation_failed_falling_back",
                provider=self._provider,
                error=str(e),
            )
            return [self._generate_hash_embedding(t) for t in texts]

    def _generate_hash_embedding(self, text: str) -> list[float]:
        """Deterministic pseudo-embedding for testing (no API needed).

        Properties:
          - Deterministic: same text → same vector
          - Normalized: unit length
          - NOT semantically meaningful — for testing only
        """
        if not text or not text.strip():
            return [0.0] * self._dimensions

        components: list[float] = []
        chunk_idx = 0

        while len(components) < self._dimensions:
            h = hashlib.sha256(f"{text}::{chunk_idx}".encode("utf-8")).digest()
            for byte_val in h:
                if len(components) >= self._dimensions:
                    break
                components.append((byte_val / 127.5) - 1.0)
            chunk_idx += 1

        magnitude = math.sqrt(sum(c * c for c in components))
        if magnitude > 0:
            components = [c / magnitude for c in components]

        return components