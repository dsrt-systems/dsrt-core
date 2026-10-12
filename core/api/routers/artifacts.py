"""
/api/v1/artifacts and /api/v1/executions/{id}/artifacts endpoints.

Exposes the durable outputs produced by agent executions.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.api.dependencies import get_security_context, get_session
from core.api.errors.exceptions import NotFoundError
from core.security.context import SecurityContext
from core.storage.models import Artifact as ArtifactORM
from core.storage.models import Execution as ExecutionORM
from schemas.api.artifacts import ArtifactListResponse
from schemas.domain import Artifact


router = APIRouter(tags=["artifacts"])


@router.get(
    "/api/v1/executions/{execution_id}/artifacts",
    response_model=ArtifactListResponse,
    summary="List all artifacts produced by an execution.",
)
async def list_execution_artifacts(
    execution_id: str,
    session: AsyncSession = Depends(get_session),
    context: SecurityContext = Depends(get_security_context),
) -> ArtifactListResponse:
    """Fetch metadata for all artifacts generated during a specific execution."""
    
    # 1. Verify execution exists and user has access via organization
    exe_result = await session.execute(
        select(ExecutionORM).where(ExecutionORM.id == execution_id)
    )
    exe = exe_result.scalar_one_or_none()
    
    if not exe or not context.is_member_of(exe.organization_id):
        raise NotFoundError(f"Execution '{execution_id}' not found.")

    # 2. Fetch artifacts
    art_result = await session.execute(
        select(ArtifactORM)
        .where(ArtifactORM.execution_id == execution_id)
        .order_by(ArtifactORM.created_at.asc())
    )
    artifacts_orm = art_result.scalars().all()
    
    artifacts = [Artifact.model_validate(a, from_attributes=True) for a in artifacts_orm]
    
    return ArtifactListResponse(artifacts=artifacts, total=len(artifacts))


@router.get(
    "/api/v1/artifacts/{artifact_id}",
    response_model=Artifact,
    summary="Get artifact metadata by ID.",
)
async def get_artifact(
    artifact_id: str,
    session: AsyncSession = Depends(get_session),
    context: SecurityContext = Depends(get_security_context),
) -> Artifact:
    """Fetch specific artifact metadata. (Content download is handled by storage layer)."""
    
    result = await session.execute(
        select(ArtifactORM).where(ArtifactORM.id == artifact_id)
    )
    art = result.scalar_one_or_none()
    
    if not art or not context.is_member_of(art.organization_id):
        raise NotFoundError(f"Artifact '{artifact_id}' not found.")
        
    return Artifact.model_validate(art, from_attributes=True)