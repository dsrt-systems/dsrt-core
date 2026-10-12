"""
/api/v1/capabilities endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from core.api.dependencies import (
    get_security_context,
    get_session,
)
from core.capabilities.registry import CapabilityRegistry
from core.repositories import CapabilityRepository
from core.security.context import SecurityContext
from schemas.api.capabilities import CapabilityListResponse
from schemas.domain import Capability, CapabilityCreate


router = APIRouter(prefix="/api/v1/capabilities", tags=["capabilities"])


def get_capability_registry(session=Depends(get_session)) -> CapabilityRegistry:
    return CapabilityRegistry(CapabilityRepository(session))


@router.get("", response_model=CapabilityListResponse, summary="List system capabilities.")
async def list_capabilities(
    registry: CapabilityRegistry = Depends(get_capability_registry),
    context: SecurityContext = Depends(get_security_context),
) -> CapabilityListResponse:
    caps = await registry.list_all()
    return CapabilityListResponse(capabilities=caps, total=len(caps))


@router.get("/{slug}", response_model=Capability, summary="Get a capability by slug.")
async def get_capability(
    slug: str,
    registry: CapabilityRegistry = Depends(get_capability_registry),
    context: SecurityContext = Depends(get_security_context),
) -> Capability:
    return await registry.get_by_slug(slug)


@router.post(
    "",
    response_model=Capability,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new system capability (Admin/System).",
)
async def create_capability(
    body: CapabilityCreate,
    registry: CapabilityRegistry = Depends(get_capability_registry),
    context: SecurityContext = Depends(get_security_context),
) -> Capability:
    return await registry.register_capability(body)