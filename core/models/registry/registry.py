"""
Model Registry Service (C2 §6, §7).

Manages the catalog of providers and models available to the Intelligence Fabric.
Extracts strongly-typed profiles (capabilities, context limits, pricing) from
the underlying ORM JSON blob.
"""

from __future__ import annotations

from core.api.errors.exceptions import ConflictError, NotFoundError
from core.observability.logging import get_logger
from core.repositories import ProviderRepository
from core.storage.models import Model as ModelORM
from schemas.domain import (
    Model,
    ModelCreate,
    Provider,
    ProviderCreate,
)


logger = get_logger("dsrt.models.registry")


class ModelRegistry:
    """Service for provider and model discovery and registration."""

    def __init__(self, provider_repo: ProviderRepository) -> None:
        self._repo = provider_repo

    # --- Providers ---

    async def register_provider(self, data: ProviderCreate) -> Provider:
        existing = await self._repo.get_provider_by_slug(data.slug)
        if existing:
            raise ConflictError(
                f"Provider '{data.slug}' already exists.",
                metadata={"slug": data.slug},
            )

        provider_orm = await self._repo.create_provider(
            slug=data.slug,
            name=data.name,
            description=data.description,
            provider_type=data.provider_type.value,
            configuration=data.configuration,
        )
        logger.info("provider_registered", slug=data.slug, provider_id=provider_orm.id)
        return Provider.model_validate(provider_orm, from_attributes=True)

    async def list_providers(self) -> list[Provider]:
        providers = await self._repo.list_providers()
        return [Provider.model_validate(p, from_attributes=True) for p in providers]

    async def get_provider(self, provider_id: str) -> Provider:
        provider = await self._repo.get_provider_by_id(provider_id)
        if not provider:
            raise NotFoundError(f"Provider '{provider_id}' not found.")
        return Provider.model_validate(provider, from_attributes=True)

    # --- Models ---

    async def register_model(self, data: ModelCreate) -> Model:
        provider = await self._repo.get_provider_by_id(data.provider_id)
        if not provider:
            raise NotFoundError(f"Provider '{data.provider_id}' not found.")

        existing = await self._repo.get_model_by_slug(
            data.provider_id, data.slug, data.version,
        )
        if existing:
            raise ConflictError(
                f"Model '{data.slug}' version '{data.version}' already exists.",
                metadata={"slug": data.slug, "version": data.version},
            )

        # Pack the strongly-typed objects into the single JSON column.
        packed_capabilities = {
            "capabilities": data.capabilities.model_dump(),
            "context_config": data.context_config.model_dump(),
            "pricing_config": data.pricing_config.model_dump(mode="json"),
            "metadata": data.metadata,
        }

        model_orm = await self._repo.create_model(
            provider_id=data.provider_id,
            slug=data.slug,
            name=data.name,
            model_identifier=data.model_identifier,
            version=data.version,
            capabilities=packed_capabilities,
        )
        logger.info(
            "model_registered", 
            slug=data.slug, 
            version=data.version, 
            model_id=model_orm.id
        )
        return self._to_model_schema(model_orm)

    async def list_models(self, provider_id: str | None = None) -> list[Model]:
        models = await self._repo.list_models(provider_id=provider_id)
        return [self._to_model_schema(m) for m in models]

    async def get_model(self, model_id: str) -> Model:
        model_orm = await self._repo.get_model_by_id(model_id)
        if not model_orm:
            raise NotFoundError(f"Model '{model_id}' not found.")
        return self._to_model_schema(model_orm)

    @staticmethod
    def _to_model_schema(orm: ModelORM) -> Model:
        """Unpack the ORM JSON column into the strongly-typed Pydantic model."""
        data = orm.capabilities or {}
        return Model(
            id=orm.id,
            provider_id=orm.provider_id,
            slug=orm.slug,
            name=orm.name,
            model_identifier=orm.model_identifier,
            version=orm.version,
            status=orm.status,
            capabilities=data.get("capabilities", {}),
            context_config=data.get("context_config", {"max_input_tokens": 1, "max_output_tokens": 1}),
            pricing_config=data.get("pricing_config", {}),
            metadata=data.get("metadata", {}),
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )