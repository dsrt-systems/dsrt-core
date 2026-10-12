"""API schemas for /providers and /models endpoints."""

from __future__ import annotations

from schemas.domain.base import DSRTSchema
from schemas.domain.provider import Model, Provider


class ProviderListResponse(DSRTSchema):
    providers: list[Provider]
    total: int


class ModelListResponse(DSRTSchema):
    models: list[Model]
    total: int