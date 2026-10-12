"""
/api/v1/providers and /api/v1/models endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from core.api.dependencies import get_security_context, get_session
from core.models.registry.registry import ModelRegistry
from core.repositories import ProviderRepository
from core.security.context import SecurityContext
from schemas.api.models import ModelListResponse, ProviderListResponse
from schemas.domain import Model, ModelCreate, Provider, ProviderCreate


router = APIRouter(tags=["model_fabric"])


def get_model_registry(session=Depends(get_session)) -> ModelRegistry:
    return ModelRegistry(ProviderRepository(session))


# --- Providers ---

@router.get("/api/v1/providers", response_model=ProviderListResponse)
async def list_providers(
    registry: ModelRegistry = Depends(get_model_registry),
    context: SecurityContext = Depends(get_security_context),
) -> ProviderListResponse:
    providers = await registry.list_providers()
    return ProviderListResponse(providers=providers, total=len(providers))


@router.post("/api/v1/providers", response_model=Provider, status_code=status.HTTP_201_CREATED)
async def create_provider(
    body: ProviderCreate,
    registry: ModelRegistry = Depends(get_model_registry),
    context: SecurityContext = Depends(get_security_context),
) -> Provider:
    # Requires Admin/System permissions (enforced by C1.4 PermissionEngine in later phases)
    return await registry.register_provider(body)


# --- Models ---

@router.get("/api/v1/models", response_model=ModelListResponse)
async def list_models(
    provider_id: str | None = None,
    registry: ModelRegistry = Depends(get_model_registry),
    context: SecurityContext = Depends(get_security_context),
) -> ModelListResponse:
    models = await registry.list_models(provider_id=provider_id)
    return ModelListResponse(models=models, total=len(models))


@router.get("/api/v1/models/{model_id}", response_model=Model)
async def get_model(
    model_id: str,
    registry: ModelRegistry = Depends(get_model_registry),
    context: SecurityContext = Depends(get_security_context),
) -> Model:
    return await registry.get_model(model_id)


@router.post("/api/v1/models", response_model=Model, status_code=status.HTTP_201_CREATED)
async def create_model(
    body: ModelCreate,
    registry: ModelRegistry = Depends(get_model_registry),
    context: SecurityContext = Depends(get_security_context),
) -> Model:
    return await registry.register_model(body)