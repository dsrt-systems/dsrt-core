"""
Verification SDK Contract (C1 §26).

Agents can REQUEST verification. Core owns the verification infrastructure.
Full verification fabric arrives in C6.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SDKVerificationResult:
    """Canonical verification result."""

    subject_id: str
    policy_id: str
    status: str  # "PASSED" | "PASSED_WITH_WARNINGS" | "FAILED" | "INCONCLUSIVE" | "REVIEW_REQUIRED"
    summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)


class VerificationSDK(Protocol):
    """Verification SDK — independent correctness assessment."""

    async def verify(
        self,
        subject_id: str,
        policy_id: str,
        subject_type: str = "artifact",
    ) -> SDKVerificationResult:
        """Request verification for a subject under a named policy."""
        ...