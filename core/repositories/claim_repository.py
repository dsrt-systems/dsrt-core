"""Claim repository — claims, evidence links, and claim verifications."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.repositories.base import Repository
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.claim import (
    ClaimEvidenceORM,
    ClaimORM,
    ClaimVerificationORM,
)
from core.storage.models.evidence import EvidenceORM
from core.storage.models.mixins import utcnow


class ClaimRepository(Repository):

    # ------------------------------------------------------------------
    # Claims
    # ------------------------------------------------------------------

    async def create(
        self,
        *,
        organization_id: str,
        execution_id: str,
        statement: str,
        source_refs: list[str] | None = None,
        importance: str = "normal",
        node_execution_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ClaimORM:
        claim = ClaimORM(
            organization_id=organization_id,
            execution_id=execution_id,
            node_execution_id=node_execution_id,
            statement=statement,
            source_refs=source_refs or [],
            importance=importance,
            status="EXTRACTED",
            uncertainty="UNKNOWN",
            metadata_json=metadata or {},
        )
        self._session.add(claim)
        await self._session.flush()
        return claim

    async def get_by_id(self, claim_id: str) -> ClaimORM | None:
        res = await self._session.execute(
            select(ClaimORM).where(ClaimORM.id == claim_id)
        )
        return res.scalar_one_or_none()

    async def find_by_statement(
        self, *, execution_id: str, statement: str,
    ) -> ClaimORM | None:
        """Exact-statement dedup within an execution."""
        res = await self._session.execute(
            select(ClaimORM).where(
                ClaimORM.execution_id == execution_id,
                ClaimORM.statement == statement,
            )
        )
        return res.scalars().first()

    async def list_for_execution(
        self,
        *,
        execution_id: str,
        organization_id: str,
        limit: int = 200,
    ) -> list[ClaimORM]:
        stmt = (
            select(ClaimORM)
            .where(
                ClaimORM.organization_id == organization_id,
                ClaimORM.execution_id == execution_id,
            )
            .order_by(ClaimORM.created_at.asc())
            .limit(limit)
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def update_status(
        self,
        claim: ClaimORM,
        status: str,
        uncertainty: str | None = None,
    ) -> ClaimORM:
        claim.status = status
        if uncertainty is not None:
            claim.uncertainty = uncertainty
        await self._session.flush()
        return claim

    # ------------------------------------------------------------------
    # Claim ↔ Evidence links
    # ------------------------------------------------------------------

    async def link_evidence(
        self,
        *,
        claim_id: str,
        evidence_id: str,
        link_type: str = "supports",
    ) -> ClaimEvidenceORM:
        """Create the link atomically and idempotently.

        Uses INSERT ... ON CONFLICT DO NOTHING against the unique
        (claim_id, evidence_id) index, then returns the surviving row —
        no check-then-insert race window.
        """
        stmt = (
            pg_insert(ClaimEvidenceORM)
            .values(
                id=new_id(IdPrefix.CLAIM_EVIDENCE),
                claim_id=claim_id,
                evidence_id=evidence_id,
                link_type=link_type,
                created_at=utcnow(),
            )
            .on_conflict_do_nothing(index_elements=["claim_id", "evidence_id"])
        )
        await self._session.execute(stmt)
        res = await self._session.execute(
            select(ClaimEvidenceORM).where(
                ClaimEvidenceORM.claim_id == claim_id,
                ClaimEvidenceORM.evidence_id == evidence_id,
            )
        )
        return res.scalar_one()

    async def get_evidence_for_claim(
        self, claim_id: str,
    ) -> list[tuple[ClaimEvidenceORM, EvidenceORM]]:
        stmt = (
            select(ClaimEvidenceORM, EvidenceORM)
            .join(EvidenceORM, ClaimEvidenceORM.evidence_id == EvidenceORM.id)
            .where(ClaimEvidenceORM.claim_id == claim_id)
        )
        res = await self._session.execute(stmt)
        return [(link, ev) for link, ev in res.all()]

    # ------------------------------------------------------------------
    # Claim verifications
    # ------------------------------------------------------------------

    async def create_verification(
        self,
        *,
        claim_id: str,
        organization_id: str,
        status: str,
        reason: str = "",
        supporting_evidence: list[str] | None = None,
        contradicting_evidence: list[str] | None = None,
        uncertainty: str = "UNKNOWN",
        verification_run_id: str | None = None,
    ) -> ClaimVerificationORM:
        ver = ClaimVerificationORM(
            claim_id=claim_id,
            organization_id=organization_id,
            verification_run_id=verification_run_id,
            status=status,
            reason=reason,
            supporting_evidence=supporting_evidence or [],
            contradicting_evidence=contradicting_evidence or [],
            uncertainty=uncertainty,
        )
        self._session.add(ver)
        await self._session.flush()
        return ver

    async def get_latest_verification(
        self, claim_id: str,
    ) -> ClaimVerificationORM | None:
        stmt = (
            select(ClaimVerificationORM)
            .where(ClaimVerificationORM.claim_id == claim_id)
            .order_by(ClaimVerificationORM.created_at.desc())
            .limit(1)
        )
        res = await self._session.execute(stmt)
        return res.scalars().first()