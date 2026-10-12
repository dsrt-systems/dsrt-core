"""
Provider Adapter Registry.
"""

from __future__ import annotations

from core.providers.base.adapter import ModelProviderAdapter
from core.providers.google.adapter import GoogleAdapter
from core.providers.openai.adapter import OpenAIAdapter


class ProviderAdapterRegistry:
    """Registry of active provider adapters."""

    def __init__(self) -> None:
        self._adapters: dict[str, ModelProviderAdapter] = {
            "openai": OpenAIAdapter(),
            "google": GoogleAdapter(),
        }

    def get_adapter(self, slug: str) -> ModelProviderAdapter | None:
        """Retrieve the adapter for a given provider slug.

        Supports exact match ('openai') or prefix match ('openai_c9d6537c').
        """
        if slug in self._adapters:
            return self._adapters[slug]

        # Prefix matching for dynamic provider slugs
        slug_lower = slug.lower()
        for base_slug, adapter in self._adapters.items():
            if slug_lower.startswith(base_slug):
                return adapter

        return None

    def register_adapter(self, slug: str, adapter: ModelProviderAdapter) -> None:
        """Register a custom adapter."""
        self._adapters[slug] = adapter


adapter_registry = ProviderAdapterRegistry()