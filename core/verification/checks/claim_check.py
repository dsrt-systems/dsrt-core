"""
Claim Evidence Check (C6 §14-15, §19).

Validates that claims have supporting evidence.
Deterministic — checks evidence linkage and contradiction flags.

Expected inputs:
  - inputs["claims"]: list of claim dicts with "id", "statement", "source_refs", "status"
  - inputs["evidence"]: list of evidence dicts with "id", "source_ref", "content"
  - inputs["contradictions"]: list of contradiction dicts (from C4)
"""

from __future__ import annotations

from typing import Any

from schemas.domain.enums import CheckType
from schemas.domain.verification import VerificationPolicy

from core.verification.checks.base import BaseCheck


class ClaimEvidenceCheck(BaseCheck):
    """Validates claim-evidence linkage (C6 §14-15)."""

    @property
    def check_type(self) -> str:
        return CheckType.CLAIM_SUPPORTED.value

    async def execute(
        self,
        subject_type: str,
        subject_id: str,
        inputs: dict[str, Any],
        policy: VerificationPolicy,
    ):
        claims = inputs.get("claims", [])
        evidence = inputs.get("evidence", [])
        contradictions = inputs.get("contradictions", [])

        if not claims:
            return self._inconclusive(
                summary="No claims provided for evidence verification.",
            )

        evidence_ids = {e.get("id") for e in evidence if e.get("id")}
        evidence_refs = {e.get("source_ref") for e in evidence if e.get("source_ref")}

        unsupported: list[str] = []
        contradicted: list[str] = []
        supported: list[str] = []

        for claim in claims:
            claim_id = claim.get("id", "unknown")
            source_refs = claim.get("source_refs", [])
            status = claim.get("status", "EXTRACTED")

            # Check if claim has linked evidence
            has_evidence = False
            for ref in source_refs:
                if ref in evidence_ids or ref in evidence_refs:
                    has_evidence = True
                    break

            if not has_evidence and source_refs:
                unsupported.append(claim_id)
            elif not source_refs:
                unsupported.append(claim_id)
            else:
                supported.append(claim_id)

            # Check contradictions (from C4)
            for contradiction in contradictions:
                mem_a = contradiction.get("memory_a_id", "")
                mem_b = contradiction.get("memory_b_id", "")
                if claim_id in (mem_a, mem_b):
                    contradicted.append(claim_id)

        total = len(claims)
        threshold = policy.thresholds.evidence_coverage
        coverage = len(supported) / total if total > 0 else 0.0

        details = {
            "total_claims": total,
            "supported": supported,
            "unsupported": unsupported,
            "contradicted": contradicted,
            "coverage": round(coverage, 3),
            "threshold": threshold,
        }

        if contradicted:
            return self._failed(
                summary=(
                    f"{len(contradicted)} claim(s) contradicted, "
                    f"{len(unsupported)} unsupported."
                ),
                details=details,
            )

        if coverage < threshold:
            return self._failed(
                summary=(
                    f"Evidence coverage {coverage:.0%} below "
                    f"threshold {threshold:.0%}."
                ),
                details=details,
            )

        if unsupported:
            return self._warning(
                summary=(
                    f"Evidence coverage {coverage:.0%}. "
                    f"{len(unsupported)} claim(s) lack evidence."
                ),
                details=details,
            )

        return self._passed(
            summary=f"All {total} claims have supporting evidence.",
            details=details,
        )