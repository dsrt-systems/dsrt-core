"""
Citation Verification Check (C6 §18).

Validates that citations exist and reference valid sources.
Deterministic — checks citation format and source linkage.

Expected inputs:
  - inputs["citations"]: list of citation dicts with "id", "source_ref", "claim_id"
  - inputs["sources"]: list of source dicts with "id", "url", "content"
"""

from __future__ import annotations

from typing import Any

from schemas.domain.enums import CheckType
from schemas.domain.verification import VerificationPolicy

from core.verification.checks.base import BaseCheck


class CitationCheck(BaseCheck):
    """Validates citation integrity (C6 §18)."""

    @property
    def check_type(self) -> str:
        return CheckType.CITATION_VALID.value

    async def execute(
        self,
        subject_type: str,
        subject_id: str,
        inputs: dict[str, Any],
        policy: VerificationPolicy,
    ):
        citations = inputs.get("citations", [])
        sources = inputs.get("sources", [])

        if not citations:
            return self._inconclusive(
                summary="No citations provided for verification.",
            )

        source_ids = {s.get("id") for s in sources if s.get("id")}
        source_refs = {s.get("url", s.get("source_ref", "")) for s in sources}

        valid: list[str] = []
        invalid: list[str] = []
        missing: list[str] = []

        for citation in citations:
            cit_id = citation.get("id", "unknown")
            source_ref = citation.get("source_ref", "")

            if not source_ref:
                missing.append(cit_id)
                continue

            if source_ref in source_ids or source_ref in source_refs:
                valid.append(cit_id)
            else:
                invalid.append(cit_id)

        total = len(citations)
        details = {
            "total_citations": total,
            "valid": valid,
            "invalid": invalid,
            "missing_source": missing,
        }

        if invalid or missing:
            error_count = len(invalid) + len(missing)
            return self._failed(
                summary=(
                    f"{error_count}/{total} citations invalid or missing sources."
                ),
                details=details,
            )

        return self._passed(
            summary=f"All {total} citations reference valid sources.",
            details=details,
        )