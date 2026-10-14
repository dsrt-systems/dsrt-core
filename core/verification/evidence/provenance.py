"""
Evidence Provenance Tracker (C6 §17, §35).

Builds and validates the full provenance chain for evidence and claims.

Evidence Chain (C6 §17):
    Final Claim
         │
         ▼
    Evidence
         │
         ▼
    Source
         │
         ▼
    Captured At
         │
         ▼
    Extraction Method
         │
         ▼
    Verification

This module provides:
  - Chain construction from claim to original source
  - Chain validation (no broken links)
  - Provenance metadata enrichment
  - Audit trail generation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.observability.logging import get_logger
from core.verification.evidence.store import EvidenceStore


logger = get_logger("dsrt.verification.provenance")


@dataclass
class ProvenanceLink:
    """A single link in the provenance chain."""
    entity_type: str  # "claim", "evidence", "source", "tool_execution", "artifact"
    entity_id: str
    description: str = ""
    timestamp: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProvenanceChain:
    """Complete provenance chain from claim to original source."""
    claim_id: str
    claim_statement: str
    links: list[ProvenanceLink] = field(default_factory=list)
    is_complete: bool = False
    broken_links: list[str] = field(default_factory=list)

    @property
    def depth(self) -> int:
        """Number of links in the chain."""
        return len(self.links)

    @property
    def source_types(self) -> list[str]:
        """All source types in the chain."""
        return [link.entity_type for link in self.links]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the chain for API responses."""
        return {
            "claim_id": self.claim_id,
            "claim_statement": self.claim_statement,
            "depth": self.depth,
            "is_complete": self.is_complete,
            "broken_links": self.broken_links,
            "links": [
                {
                    "entity_type": link.entity_type,
                    "entity_id": link.entity_id,
                    "description": link.description,
                    "timestamp": link.timestamp,
                    "metadata": link.metadata,
                }
                for link in self.links
            ],
        }


class EvidenceProvenanceTracker:
    """Builds and validates evidence provenance chains (C6 §17).

    Usage:
        tracker = EvidenceProvenanceTracker(session)
        chain = await tracker.build_chain(claim_id="clm_1")
        if chain.is_complete:
            print("Full provenance verified")
        else:
            print(f"Broken links: {chain.broken_links}")
    """

    def __init__(
        self,
        session: AsyncSession,
        evidence_store: EvidenceStore | None = None,
    ) -> None:
        self._session = session
        self._store = evidence_store or EvidenceStore(session)

    async def build_chain(
        self,
        claim_id: str,
    ) -> ProvenanceChain:
        """Build the full provenance chain for a claim (C6 §17).

        Traverses: Claim → Evidence → Source → Capture → Extraction

        Returns:
            ProvenanceChain with all links and completeness status.
        """
        claim = await self._store.get_claim(claim_id)
        if not claim:
            return ProvenanceChain(
                claim_id=claim_id,
                claim_statement="(claim not found)",
                is_complete=False,
                broken_links=["claim_not_found"],
            )

        chain = ProvenanceChain(
            claim_id=claim_id,
            claim_statement=claim.statement,
        )

        # Link 1: The claim itself
        chain.links.append(ProvenanceLink(
            entity_type="claim",
            entity_id=claim.id,
            description=f"Claim: {claim.statement[:100]}",
            timestamp=claim.created_at.isoformat() if claim.created_at else None,
            metadata={
                "status": claim.status,
                "importance": claim.importance,
                "uncertainty": claim.uncertainty,
            },
        ))

        # Link 2: Evidence items linked to the claim
        evidence_items = await self._store.get_evidence_for_claim(claim_id)

        if not evidence_items:
            chain.broken_links.append("no_evidence_linked")
            chain.is_complete = False
            return chain

        for ev in evidence_items:
            # Link: Evidence
            chain.links.append(ProvenanceLink(
                entity_type="evidence",
                entity_id=ev["evidence_id"],
                description=f"Evidence from {ev['source_type']}",
                timestamp=ev.get("captured_at"),
                metadata={
                    "link_type": ev["link_type"],
                    "verification_status": ev["verification_status"],
                },
            ))

            # Link: Source
            chain.links.append(ProvenanceLink(
                entity_type="source",
                entity_id=ev["source_ref"],
                description=f"Source: {ev['source_type']}:{ev['source_ref'][:80]}",
                metadata={
                    "source_type": ev["source_type"],
                    "content_preview": ev.get("extracted_content", "")[:200],
                },
            ))

        # Link 3: Verification records
        verifications = await self._store.get_claim_verifications(claim_id)
        for v in verifications:
            chain.links.append(ProvenanceLink(
                entity_type="verification",
                entity_id=v.id,
                description=f"Verification: {v.status}",
                timestamp=v.created_at.isoformat() if v.created_at else None,
                metadata={
                    "status": v.status,
                    "uncertainty": v.uncertainty,
                    "verification_run_id": v.verification_run_id,
                    "reason": v.reason[:200] if v.reason else "",
                },
            ))

        # Determine completeness
        has_evidence = len(evidence_items) > 0
        has_verification = len(verifications) > 0

        chain.is_complete = has_evidence and has_verification

        if not has_evidence:
            chain.broken_links.append("no_evidence")
        if not has_verification:
            chain.broken_links.append("no_verification")

        logger.info(
            "provenance_chain_built",
            claim_id=claim_id,
            depth=chain.depth,
            is_complete=chain.is_complete,
            broken_links=chain.broken_links,
        )

        return chain

    async def validate_chain(
        self,
        claim_id: str,
    ) -> dict[str, Any]:
        """Validate a claim's provenance chain and return a report.

        Returns:
            Dict with validation results and recommendations.
        """
        chain = await self.build_chain(claim_id)

        issues: list[str] = []
        recommendations: list[str] = []

        if not chain.is_complete:
            for broken in chain.broken_links:
                issues.append(f"Broken link: {broken}")
                if broken == "no_evidence_linked":
                    recommendations.append(
                        "Attach evidence to this claim using "
                        "sdk.verification.attach_evidence()."
                    )
                elif broken == "no_verification":
                    recommendations.append(
                        "Run verification on this claim using "
                        "sdk.verification.verify()."
                    )

        # Check for contradictory evidence
        evidence_items = await self._store.get_evidence_for_claim(claim_id)
        contradicting = [
            e for e in evidence_items if e["link_type"] == "contradicts"
        ]
        if contradicting:
            issues.append(
                f"{len(contradicting)} contradicting evidence item(s) found."
            )
            recommendations.append(
                "Review contradicting evidence and resolve the conflict."
            )

        # Check for outdated evidence
        for ev in evidence_items:
            if ev.get("verification_status") == "EXPIRED":
                issues.append(
                    f"Evidence '{ev['evidence_id']}' is expired."
                )
                recommendations.append(
                    "Refresh expired evidence with current data."
                )

        return {
            "claim_id": claim_id,
            "is_valid": len(issues) == 0,
            "chain_depth": chain.depth,
            "is_complete": chain.is_complete,
            "issues": issues,
            "recommendations": recommendations,
        }

    async def get_execution_provenance_summary(
        self,
        execution_id: str,
    ) -> dict[str, Any]:
        """Get a provenance summary for all claims in an execution."""
        claims = await self._store.list_claims_for_execution(execution_id)

        complete_chains = 0
        broken_chains = 0
        total_evidence = 0

        for claim in claims:
            evidence = await self._store.get_evidence_for_claim(claim.id)
            total_evidence += len(evidence)

            verifications = await self._store.get_claim_verifications(claim.id)
            if evidence and verifications:
                complete_chains += 1
            else:
                broken_chains += 1

        return {
            "execution_id": execution_id,
            "total_claims": len(claims),
            "complete_provenance_chains": complete_chains,
            "broken_provenance_chains": broken_chains,
            "total_evidence_items": total_evidence,
            "provenance_coverage": (
                complete_chains / len(claims) if claims else 0.0
            ),
        }