"""
Provider and Model Repository.

Data access for the Model Fabric Registry.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.repositories.base import Repository
from core.storage.models import Model, Provider


class ProviderRepository(Repository):
    # --- Providers ---

    async def get_provider_by_id(self, provider_id: str) -> Provider | None:
        result = await self._session.execute(
            select(Provider).where(Provider.id == provider_id)
        )
        return result.scalar_one_or_none()

    async def get_provider_by_slug(self, slug: str) -> Provider | None:
        result = await self._session.execute(
            select(Provider).where(Provider.slug == slug)
        )
        return result.scalar_one_or_none()

    async def list_providers(self) -> list[Provider]:
        result = await self._session.execute(
            select(Provider).order_by(Provider.name)
        )
        return list(result.scalars().all())

    async def create_provider(
        self,
        *,
        slug: str,
        name: str,
        provider_type: str,
        description: str = "",
        configuration: dict | None = None,
    ) -> Provider:
        provider = Provider(
            slug=slug,
            name=name,
            description=description,
            provider_type=provider_type,
            configuration=configuration or {},
            status="active",
        )
        self._session.add(provider)
        await self._session.flush()
        return provider

    # --- Models ---

    async def get_model_by_id(self, model_id: str) -> Model | None:
        result = await self._session.execute(
            select(Model)
            .options(selectinload(Model.provider))
            .where(Model.id == model_id)
        )
        return result.scalar_one_or_none()

    async def get_model_by_slug(
        self, provider_id: str, slug: str, version: str
    ) -> Model | None:
        result = await self._session.execute(
            select(Model)
            .options(selectinload(Model.provider))
            .where(
                Model.provider_id == provider_id,
                Model.slug == slug,
                Model.version == version,
            )
        )
        return result.scalar_one_or_none()

    async def list_models(
        self, provider_id: str | None = None, active_only: bool = True
    ) -> list[Model]:
        stmt = select(Model).options(selectinload(Model.provider))
        if provider_id:
            stmt = stmt.where(Model.provider_id == provider_id)
        if active_only:
            stmt = stmt.where(Model.status == "active")
            
        result = await self._session.execute(stmt.order_by(Model.name))
        return list(result.scalars().all())

    async def create_model(
        self,
        *,
        provider_id: str,
        slug: str,
        name: str,
        model_identifier: str,
        version: str,
        capabilities: dict[str, Any],
    ) -> Model:
        model = Model(
            provider_id=provider_id,
            slug=slug,
            name=name,
            model_identifier=model_identifier,
            version=version,
            capabilities=capabilities,
            status="active",
        )
        self._session.add(model)
        await self._session.flush()
        return model