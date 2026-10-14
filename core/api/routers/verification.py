"""
Verification REST API (C6 §47).

Endpoints for verification runs, claims, evidence, and reviews.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.api.dependencies.database import get_session
from core.api.dependencies.security import (
    get_security_context,
    require_active_organization,
)
from core.kernel.kernel import ExecutionKernel
from core.repositories import (
    AgentRepository,
    CapabilityRepository,
    EventRepository,
    ExecutionRepository,
    TaskRepository,
)
from core.security.context import SecurityContext
from core.storage.models.verification import (
    VerificationCheckORM,
    VerificationRun,
)
from core.storage.models.claim import ClaimORM, ClaimVerificationORM
from core.storage.models.evidence import EvidenceORM
from core.storage.models.reliability import (
    ReliabilityIncidentORM,
    ReviewRequestORM,
)
from core.verification.engine.engine import VerificationEngine
from schemas.api.verification import (
    AttachEvidenceRequest,
    ArtifactVerificationResponse,
    ClaimResponse,
    ClaimVerificationResponse,
    CreateReviewRequest,
    CreateVerificationRequest,
    ReliabilityIncidentResponse,
    ReviewResponse,
    VerificationCheckResponse,
    VerificationRunResponse,
)
from schemas.domain.verification import VerificationRequest


router = APIRouter(prefix="/api/v1", tags=["verification"])


def _get_kernel(session: AsyncSession) -> ExecutionKernel:
    return ExecutionKernel(
        TaskRepository(session),
        ExecutionRepository(session),
        AgentRepository(session, CapabilityRepository(session)),
        EventRepository(session),
    )


# ------------------------------------------------------------------
# Verification Runs (C6 §47)
# ------------------------------------------------------------------


@router.post("/verifications", status_code=201)
async def create_verification(
    body: CreateVerificationRequest,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create and execute a verification run."""
    kernel = _get_kernel(session)
    engine = VerificationEngine(session, kernel)

    request = VerificationRequest(
        subject_type=body.subject_type,
        subject_id=body.subject_id,
        policy_id=body.policy_id,
        inputs=body.inputs,
        evidence_refs=body.evidence_refs,
        constraints=body.constraints,
        metadata={"organization_id": ctx.active_organization_id},
    )

    result = await engine.verify(request)

    return {
        "verification_run_id": result.verification_run_id,
        "status": result.status.value,
        "checks": len(result.checks),
        "failures": result.failures,
        "warnings": result.warnings,
        "dimensions": result.dimensions,
    }


@router.get("/verifications/{verification_id}")
async def get_verification(
    verification_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a verification run by ID."""
    stmt = select(VerificationRun).where(VerificationRun.id == verification_id)
    result = await session.execute(stmt)
    run = result.scalar_one_or_none()

    if not run:
        return {"error": "Verification run not found."}

    return {
        "id": run.id,
        "execution_id": run.execution_id,
        "subject_type": run.subject_type,
        "subject_id": run.subject_id,
        "policy_id": run.policy_id,
        "status": run.status,
        "engine_version": run.engine_version,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


@router.get("/verifications/{verification_id}/checks")
async def get_verification_checks(
    verification_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get all checks for a verification run."""
    stmt = (
        select(VerificationCheckORM)
        .where(VerificationCheckORM.verification_run_id == verification_id)
        .order_by(VerificationCheckORM.created_at.asc())
    )
    result = await session.execute(stmt)
    checks = list(result.scalars().all())

    return {
        "verification_run_id": verification_id,
        "checks": [
            {
                "id": c.id,
                "check_type": c.check_type,
                "evaluator": c.evaluator,
                "required": c.required,
                "status": c.status,
                "summary": c.summary,
                "uncertainty": c.uncertainty,
                "duration_ms": c.duration_ms,
            }
            for c in checks
        ],
        "total": len(checks),
    }


@router.get("/executions/{execution_id}/verification")
async def get_execution_verification(
    execution_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get all verification runs for an execution."""
    stmt = (
        select(VerificationRun)
        .where(VerificationRun.execution_id == execution_id)
        .order_by(VerificationRun.created_at.desc())
    )
    result = await session.execute(stmt)
    runs = list(result.scalars().all())

    return {
        "execution_id": execution_id,
        "verifications": [
            {
                "id": r.id,
                "subject_type": r.subject_type,
                "subject_id": r.subject_id,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in runs
        ],
        "total": len(runs),
    }


# ------------------------------------------------------------------
# Claims (C6 §47)
# ------------------------------------------------------------------


@router.get("/claims/{claim_id}")
async def get_claim(
    claim_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a claim by ID."""
    stmt = select(ClaimORM).where(ClaimORM.id == claim_id)
    result = await session.execute(stmt)
    claim = result.scalar_one_or_none()

    if not claim:
        return {"error": "Claim not found."}

    return {
        "id": claim.id,
        "execution_id": claim.execution_id,
        "statement": claim.statement,
        "importance": claim.importance,
        "status": claim.status,
        "uncertainty": claim.uncertainty,
        "source_refs": claim.source_refs,
    }


@router.get("/claims/{claim_id}/verification")
async def get_claim_verification(
    claim_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get verification results for a claim."""
    stmt = (
        select(ClaimVerificationORM)
        .where(ClaimVerificationORM.claim_id == claim_id)
        .order_by(ClaimVerificationORM.created_at.desc())
    )
    result = await session.execute(stmt)
    verifications = list(result.scalars().all())

    return {
        "claim_id": claim_id,
        "verifications": [
            {
                "id": v.id,
                "status": v.status,
                "reason": v.reason,
                "supporting_evidence": v.supporting_evidence,
                "contradicting_evidence": v.contradicting_evidence,
                "uncertainty": v.uncertainty,
            }
            for v in verifications
        ],
        "total": len(verifications),
    }


# ------------------------------------------------------------------
# Reviews (C6 §47)
# ------------------------------------------------------------------


@router.post("/verifications/{verification_id}/review")
async def create_review(
    verification_id: str,
    body: CreateReviewRequest,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a human review request for a verification."""
    from core.verification.review.requests import ReviewManager

    mgr = ReviewManager(session, _get_kernel(session))
    review = await mgr.create_review(
        verification_run_id=verification_id,
        reason=body.reason,
        reviewer_role=body.reviewer_role,
        evidence_refs=body.evidence_refs,
    )

    return {
        "review_id": review.id,
        "verification_run_id": verification_id,
        "status": review.status,
        "reviewer_role": review.reviewer_role,
        "expires_at": review.expires_at.isoformat() if review.expires_at else None,
    }


# ------------------------------------------------------------------
# Reliability Incidents
# ------------------------------------------------------------------


@router.get("/executions/{execution_id}/incidents")
async def get_execution_incidents(
    execution_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get reliability incidents for an execution."""
    stmt = (
        select(ReliabilityIncidentORM)
        .where(ReliabilityIncidentORM.execution_id == execution_id)
        .order_by(ReliabilityIncidentORM.created_at.desc())
    )
    result = await session.execute(stmt)
    incidents = list(result.scalars().all())

    return {
        "execution_id": execution_id,
        "incidents": [
            {
                "id": i.id,
                "category": i.category,
                "severity": i.severity,
                "description": i.description,
                "detected_by": i.detected_by,
                "recovery_action": i.recovery_action,
                "resolved": i.resolved,
            }
            for i in incidents
        ],
        "total": len(incidents),
    }