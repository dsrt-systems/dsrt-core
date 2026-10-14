"""Evidence repository — tenant-scoped persistence for evidence records."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from core.repositories.base import Repository
from core.storage.models.evidence import EvidenceORM


class EvidenceRepository(Repository):

    async def create(
        self,
        *,
        organization_id: str,
        source_type: str,
        source_ref: str,
        execution_id: str | None = None,
        location: str | None = None,
        extracted_content: str = "",
        captured_at: datetime | None = None,
        provenance: dict[str, Any] | None = None,
        verification_status: str = "CAPTURED",
    ) -> EvidenceORM:
        ev = EvidenceORM(
            organization_id=organization_id,
            execution_id=execution_id,
            source_type=source_type,
            source_ref=source_ref,
            location=location,
            extracted_content=extracted_content,
            captured_at=captured_at,
            provenance=provenance or {},
            verification_status=verification_status,
        )
        self._session.add(ev)
        await self._session.flush()
        return ev

    async def get_by_id(self, evidence_id: str) -> EvidenceORM | None:
        res = await self._session.execute(
            select(EvidenceORM).where(EvidenceORM.id == evidence_id)
        )
        return res.scalar_one_or_none()

    async def find_existing(
        self,
        *,
        organization_id: str,
        source_type: str,
        source_ref: str,
        execution_id: str | None,
    ) -> EvidenceORM | None:
        """Idempotent-capture lookup: (org, source_type, source_ref, execution)."""
        stmt = select(EvidenceORM).where(
            EvidenceORM.organization_id == organization_id,
            EvidenceORM.source_type == source_type,
            EvidenceORM.source_ref == source_ref,
        )
        if execution_id is None:
            stmt = stmt.where(EvidenceORM.execution_id.is_(None))
        else:
            stmt = stmt.where(EvidenceORM.execution_id == execution_id)
        res = await self._session.execute(stmt)
        return res.scalars().first()

    async def find_by_source_ref(
        self, *, organization_id: str, source_ref: str,
    ) -> EvidenceORM | None:
        stmt = (
            select(EvidenceORM)
            .where(
                EvidenceORM.organization_id == organization_id,
                EvidenceORM.source_ref == source_ref,
            )
            .order_by(EvidenceORM.created_at.desc())
            .limit(1)
        )
        res = await self._session.execute(stmt)
        return res.scalars().first()

    async def list_for_execution(
        self,
        *,
        execution_id: str,
        organization_id: str,
        limit: int = 50,
    ) -> list[EvidenceORM]:
        stmt = (
            select(EvidenceORM)
            .where(
                EvidenceORM.organization_id == organization_id,
                EvidenceORM.execution_id == execution_id,
            )
            .order_by(EvidenceORM.created_at.desc())
            .limit(limit)
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def update_status(self, evidence: EvidenceORM, status: str) -> EvidenceORM:
        evidence.verification_status = status
        await self._session.flush()
        return evidence