"""
Citation Verifier (C6 §18).

Deterministic citation verification against the org-scoped evidence store.

Outcomes:
    VALID          resolves to VERIFIED, non-expired evidence
    WEAK           resolves to evidence that is CAPTURED but not yet verified
    OUTDATED       resolves to evidence past its validity window
    INACCESSIBLE   resolves to evidence marked INACCESSIBLE
    INVALID        does not resolve in this organization, or source REJECTED
    MISSING        citation carries no source_ref at all

Whether the source actually SUPPORTS the claim is semantic verification
(C6 §12) — explicitly not claimed here; `semantic_support_checked=False`
marks the boundary until that layer exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from core.repositories.evidence_repository import EvidenceRepository
from core.verification.evidence.provenance import evidence_is_expired


@dataclass(frozen=True)
class CitationOutcome:
    citation_id: str
    source_ref: str
    outcome: str
    evidence_id: str | None = None


@dataclass(frozen=True)
class CitationVerificationSummary:
    total: int
    outcomes: list[CitationOutcome] = field(default_factory=list)
    semantic_support_checked: bool = False

    def ids_with(self, outcome: str) -> list[str]:
        return [o.citation_id for o in self.outcomes if o.outcome == outcome]


class CitationVerifier:

    def __init__(self, session: AsyncSession) -> None:
        self._evidence = EvidenceRepository(session)

    async def verify_citations(
        self,
        citations: list[dict],
        organization_id: str,
    ) -> CitationVerificationSummary:
        now = datetime.now(timezone.utc)
        outcomes: list[CitationOutcome] = []

        for i, citation in enumerate(citations):
            cit_id = (
                citation.get("id") if isinstance(citation, dict) else None
            ) or f"citation_{i}"
            source_ref = (
                citation.get("source_ref") if isinstance(citation, dict) else None
            ) or ""

            if not source_ref.strip():
                outcomes.append(
                    CitationOutcome(cit_id, "", "MISSING")
                )
                continue

            ev = await self._evidence.find_by_source_ref(
                organization_id=organization_id, source_ref=source_ref,
            )
            if ev is None:
                outcomes.append(
                    CitationOutcome(cit_id, source_ref, "INVALID")
                )
                continue

            if ev.verification_status == "INACCESSIBLE":
                outcome = "INACCESSIBLE"
            elif ev.verification_status == "REJECTED":
                outcome = "INVALID"
            elif evidence_is_expired(ev, now):
                outcome = "OUTDATED"
            elif ev.verification_status == "VERIFIED":
                outcome = "VALID"
            else:
                outcome = "WEAK"

            outcomes.append(
                CitationOutcome(cit_id, source_ref, outcome, evidence_id=ev.id)
            )

        return CitationVerificationSummary(
            total=len(citations),
            outcomes=outcomes,
            semantic_support_checked=False,
        )