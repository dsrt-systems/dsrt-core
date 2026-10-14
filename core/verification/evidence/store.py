"""
Evidence Store (C6 §16-17, §48-51).

Manages the full lifecycle of evidence and claims:
  - Evidence CRUD with provenance
  - Claim extraction and persistence
  - Claim-evidence linking
  - Claim verification recording
  - Contradiction tracking (integrates with C4 MemoryConflict)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import (
    ClaimStatus,
    EvidenceStatus,
    EventType,
    UncertaintyLevel,
)

from core.kernel.kernel import ExecutionKernel
from core.observability.logging import get_logger
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.claim import (
    ClaimEvidenceORM,
    ClaimORM,
    ClaimVerificationORM,
)
from core.storage.models.evidence import EvidenceORM


logger = get_logger("dsrt.verification.evidence")


class EvidenceStore:
    """Manages evidence and claim persistence with full provenance."""

    def __init__(
        self,
        session: AsyncSession,
        kernel: ExecutionKernel | None = None,
    ) -> None:
        self._session = session
        self._kernel = kernel

    # ------------------------------------------------------------------
    # Evidence CRUD (C6 §16)
    # ------------------------------------------------------------------

    async def create_evidence(
        self,
        *,
        execution_id: str | None = None,
        source_type: str,
        source_ref: str,
        extracted_content: str = "",
        location: str | None = None,
        provenance: dict[str, Any] | None = None,
        verification_status: str = EvidenceStatus.CAPTURED.value,
    ) -> EvidenceORM:
        evidence = EvidenceORM(
            id=new_id(IdPrefix.EVIDENCE),
            execution_id=execution_id,
            source_type=source_type,
            source_ref=source_ref,
            location=location,
            extracted_content=extracted_content,
            captured_at=datetime.now(timezone.utc),
            provenance=provenance or {},
            verification_status=verification_status,
        )
        self._session.add(evidence)
        await self._session.flush()
        logger.info(
            "evidence_created",
            evidence_id=evidence.id,
            source_type=source_type,
        )
        return evidence

    async def get_evidence(self, evidence_id: str) -> EvidenceORM | None:
        stmt = select(EvidenceORM).where(EvidenceORM.id == evidence_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_evidence_for_execution(
        self, execution_id: str, limit: int = 100,
    ) -> list[EvidenceORM]:
        stmt = (
            select(EvidenceORM)
            .where(EvidenceORM.execution_id == execution_id)
            .order_by(EvidenceORM.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update_evidence_status(
        self, evidence_id: str, status: str,
    ) -> EvidenceORM | None:
        evidence = await self.get_evidence(evidence_id)
        if not evidence:
            return None
        evidence.verification_status = status
        await self._session.flush()
        return evidence

    # ------------------------------------------------------------------
    # Claim CRUD (C6 §14)
    # ------------------------------------------------------------------

    async def create_claim(
        self,
        *,
        execution_id: str,
        statement: str,
        node_execution_id: str | None = None,
        source_refs: list[str] | None = None,
        importance: str = "normal",
        metadata: dict[str, Any] | None = None,
    ) -> ClaimORM:
        claim = ClaimORM(
            id=new_id(IdPrefix.CLAIM),
            execution_id=execution_id,
            node_execution_id=node_execution_id,
            statement=statement,
            source_refs=source_refs or [],
            importance=importance,
            status=ClaimStatus.EXTRACTED.value,
            uncertainty=UncertaintyLevel.UNKNOWN.value,
            metadata_json=metadata or {},
        )
        self._session.add(claim)
        await self._session.flush()
        await self._emit_event(
            execution_id, EventType.AGENT_EVENT,
            {"claim_event": "CLAIM_CREATED", "claim_id": claim.id},
        )
        logger.info("claim_created", claim_id=claim.id)
        return claim

    async def get_claim(self, claim_id: str) -> ClaimORM | None:
        stmt = select(ClaimORM).where(ClaimORM.id == claim_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_claims_for_execution(
        self, execution_id: str, status: str | None = None, limit: int = 100,
    ) -> list[ClaimORM]:
        stmt = select(ClaimORM).where(ClaimORM.execution_id == execution_id)
        if status:
            stmt = stmt.where(ClaimORM.status == status)
        stmt = stmt.order_by(ClaimORM.created_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update_claim_status(
        self, claim_id: str, status: str, uncertainty: str | None = None,
    ) -> ClaimORM | None:
        claim = await self.get_claim(claim_id)
        if not claim:
            return None
        claim.status = status
        if uncertainty:
            claim.uncertainty = uncertainty
        await self._session.flush()
        return claim

    # ------------------------------------------------------------------
    # Claim-Evidence Linking (C6 §17)
    # ------------------------------------------------------------------

    async def link_evidence_to_claim(
        self, claim_id: str, evidence_id: str, link_type: str = "supports",
    ) -> ClaimEvidenceORM:
        claim = await self.get_claim(claim_id)
        if not claim:
            raise ValueError(f"Claim '{claim_id}' not found.")
        evidence = await self.get_evidence(evidence_id)
        if not evidence:
            raise ValueError(f"Evidence '{evidence_id}' not found.")

        existing = await self._get_link(claim_id, evidence_id)
        if existing:
            return existing

        link = ClaimEvidenceORM(
            id=new_id(IdPrefix.CLAIM_EVIDENCE),
            claim_id=claim_id,
            evidence_id=evidence_id,
            link_type=link_type,
        )
        self._session.add(link)
        await self._session.flush()
        await self._emit_event(
            claim.execution_id, EventType.AGENT_EVENT,
            {"claim_event": "EVIDENCE_ATTACHED", "claim_id": claim_id,
             "evidence_id": evidence_id, "link_type": link_type},
        )
        logger.info("claim_evidence_linked", claim_id=claim_id, evidence_id=evidence_id)
        return link

    async def get_evidence_for_claim(
        self, claim_id: str,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(ClaimEvidenceORM, EvidenceORM)
            .join(EvidenceORM, ClaimEvidenceORM.evidence_id == EvidenceORM.id)
            .where(ClaimEvidenceORM.claim_id == claim_id)
        )
        result = await self._session.execute(stmt)
        return [
            {
                "link_id": link.id,
                "link_type": link.link_type,
                "evidence_id": ev.id,
                "source_type": ev.source_type,
                "source_ref": ev.source_ref,
                "extracted_content": ev.extracted_content[:500],
                "verification_status": ev.verification_status,
                "captured_at": ev.captured_at.isoformat() if ev.captured_at else None,
            }
            for link, ev in result.all()
        ]

    # ------------------------------------------------------------------
    # Claim Verification Recording (C6 §15)
    # ------------------------------------------------------------------

    async def record_claim_verification(
        self,
        *,
        claim_id: str,
        verification_run_id: str,
        status: str,
        reason: str = "",
        supporting_evidence: list[str] | None = None,
        contradicting_evidence: list[str] | None = None,
        uncertainty: str = UncertaintyLevel.UNKNOWN.value,
    ) -> ClaimVerificationORM:
        cv = ClaimVerificationORM(
            id=new_id(IdPrefix.CLAIM_VERIFICATION),
            claim_id=claim_id,
            verification_run_id=verification_run_id,
            status=status,
            reason=reason,
            supporting_evidence=supporting_evidence or [],
            contradicting_evidence=contradicting_evidence or [],
            uncertainty=uncertainty,
        )
        self._session.add(cv)
        claim = await self.get_claim(claim_id)
        if claim:
            claim.status = status
            claim.uncertainty = uncertainty
        await self._session.flush()
        if claim:
            await self._emit_event(
                claim.execution_id, EventType.AGENT_EVENT,
                {"claim_event": "CLAIM_VERIFIED", "claim_id": claim_id, "status": status},
            )
        logger.info("claim_verification_recorded", claim_id=claim_id, status=status)
        return cv

    async def get_claim_verifications(
        self, claim_id: str,
    ) -> list[ClaimVerificationORM]:
        stmt = (
            select(ClaimVerificationORM)
            .where(ClaimVerificationORM.claim_id == claim_id)
            .order_by(ClaimVerificationORM.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    async def get_execution_evidence_summary(
        self, execution_id: str,
    ) -> dict[str, Any]:
        ev_stmt = select(func.count(EvidenceORM.id)).where(
            EvidenceORM.execution_id == execution_id,
        )
        ev_result = await self._session.execute(ev_stmt)
        evidence_count = ev_result.scalar() or 0

        cl_stmt = (
            select(ClaimORM.status, func.count(ClaimORM.id))
            .where(ClaimORM.execution_id == execution_id)
            .group_by(ClaimORM.status)
        )
        cl_result = await self._session.execute(cl_stmt)
        claim_counts = {row[0]: row[1] for row in cl_result.all()}

        return {
            "execution_id": execution_id,
            "evidence_count": evidence_count,
            "total_claims": sum(claim_counts.values()),
            "claims_by_status": claim_counts,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_link(
        self, claim_id: str, evidence_id: str,
    ) -> ClaimEvidenceORM | None:
        stmt = select(ClaimEvidenceORM).where(
            ClaimEvidenceORM.claim_id == claim_id,
            ClaimEvidenceORM.evidence_id == evidence_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def _emit_event(
        self, execution_id: str, event_type: EventType, payload: dict[str, Any],
    ) -> None:
        if not self._kernel:
            return
        try:
            await self._kernel.emit_event(
                execution_id=execution_id,
                event_type=event_type,
                source="dsrt.verification.evidence",
                payload=payload,
            )
        except Exception as e:
            logger.warning("evidence_event_emission_failed", error=str(e))