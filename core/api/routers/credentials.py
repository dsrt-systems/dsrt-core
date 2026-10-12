"""
/api/v1/credentials endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from core.api.dependencies import (
    get_security_context,
    get_session,
    require_active_organization,
)
from core.models.credentials.manager import CredentialManager
from core.repositories.credential_repository import CredentialRepository
from core.repositories.provider_repository import ProviderRepository
from core.security.context import SecurityContext
from schemas.api.credentials import CredentialCreateRequest, CredentialListResponse
from schemas.domain.model_fabric import CredentialReference


router = APIRouter(prefix="/api/v1/credentials", tags=["credentials"])


def get_credential_manager(session=Depends(get_session)) -> CredentialManager:
    return CredentialManager(
        cred_repo=CredentialRepository(session),
        provider_repo=ProviderRepository(session),
    )


@router.get("", response_model=CredentialListResponse)
async def list_credentials(
    provider_id: str | None = None,
    manager: CredentialManager = Depends(get_credential_manager),
    context: SecurityContext = Depends(require_active_organization),
) -> CredentialListResponse:
    creds = await manager.list_credentials(
        organization_id=context.active_organization_id, provider_id=provider_id
    )
    return CredentialListResponse(credentials=creds, total=len(creds))


@router.post("", response_model=CredentialReference, status_code=status.HTTP_201_CREATED)
async def create_credential(
    body: CredentialCreateRequest,
    manager: CredentialManager = Depends(get_credential_manager),
    context: SecurityContext = Depends(require_active_organization),
) -> CredentialReference:
    return await manager.create_credential(
        organization_id=context.active_organization_id,
        provider_id=body.provider_id,
        raw_secret=body.raw_secret,
        label=body.label,
        credential_type=body.credential_type,
    )


@router.delete(
    "/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def revoke_credential(
    credential_id: str,
    manager: CredentialManager = Depends(get_credential_manager),
    context: SecurityContext = Depends(require_active_organization),
) -> Response:
    await manager.revoke_credential(
        organization_id=context.active_organization_id,
        credential_id=credential_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)