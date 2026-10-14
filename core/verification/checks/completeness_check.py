"""
Completeness Verification Check (C6 §20-21).

Validates that all task requirements are addressed in the output.
Deterministic — checks requirement coverage against produced sections.

Expected inputs:
  - inputs["requirements"]: list of requirement dicts with "id", "description", "priority"
  - inputs["output_sections"]: list of section/topic strings found in the output
  - inputs["output"]: the full output (str or dict) for keyword matching
"""

from __future__ import annotations

from typing import Any

from schemas.domain.enums import CheckType
from schemas.domain.verification import VerificationPolicy

from core.verification.checks.base import BaseCheck


class CompletenessCheck(BaseCheck):
    """Validates requirement coverage (C6 §20-21)."""

    @property
    def check_type(self) -> str:
        return CheckType.COMPLETENESS.value

    async def execute(
        self,
        subject_type: str,
        subject_id: str,
        inputs: dict[str, Any],
        policy: VerificationPolicy,
    ):
        requirements = inputs.get("requirements", [])
        output_sections = inputs.get("output_sections", [])
        output = inputs.get("output", "")

        if not requirements:
            return self._inconclusive(
                summary="No requirements provided for completeness check.",
                details={"reason": "no_requirements"},
            )

        # Build searchable text from output
        searchable = ""
        if isinstance(output, str):
            searchable = output.lower()
        elif isinstance(output, dict):
            searchable = str(output).lower()

        sections_lower = [s.lower() for s in output_sections]

        covered: list[str] = []
        missing_required: list[str] = []
        missing_optional: list[str] = []

        for req in requirements:
            req_id = req.get("id", "unknown")
            description = req.get("description", "")
            priority = req.get("priority", "required")
            keywords = req.get("keywords", [])

            # Check if requirement is covered by sections or keywords
            is_covered = False

            # Check section match
            for section in sections_lower:
                if description.lower() in section or section in description.lower():
                    is_covered = True
                    break

            # Check keyword match in output
            if not is_covered and searchable:
                for kw in keywords:
                    if kw.lower() in searchable:
                        is_covered = True
                        break

            # Check description words in output (fallback)
            if not is_covered and searchable and description:
                desc_words = [
                    w.lower() for w in description.split()
                    if len(w) > 3
                ]
                if desc_words:
                    match_count = sum(
                        1 for w in desc_words if w in searchable
                    )
                    if match_count >= len(desc_words) * 0.5:
                        is_covered = True

            if is_covered:
                covered.append(req_id)
            elif priority == "required":
                missing_required.append(req_id)
            else:
                missing_optional.append(req_id)

        total = len(requirements)
        coverage = len(covered) / total if total > 0 else 0.0
        threshold = policy.thresholds.completeness_coverage

        details = {
            "total_requirements": total,
            "covered": covered,
            "missing_required": missing_required,
            "missing_optional": missing_optional,
            "coverage": round(coverage, 3),
            "threshold": threshold,
        }

        if missing_required:
            return self._failed(
                summary=(
                    f"Completeness {coverage:.0%} below threshold {threshold:.0%}. "
                    f"{len(missing_required)} required requirement(s) missing."
                ),
                details=details,
            )

        if coverage < threshold:
            return self._failed(
                summary=(
                    f"Completeness {coverage:.0%} below threshold {threshold:.0%}."
                ),
                details=details,
            )

        if missing_optional:
            return self._warning(
                summary=(
                    f"Completeness {coverage:.0%}. "
                    f"{len(missing_optional)} optional requirement(s) missing."
                ),
                details=details,
            )

        return self._passed(
            summary=f"All {total} requirements covered ({coverage:.0%}).",
            details=details,
        )