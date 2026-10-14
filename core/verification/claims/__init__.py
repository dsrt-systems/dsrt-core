"""Claims Fabric (C6 §14-15, §18-19)."""

from core.verification.claims.citation_verifier import (
    CitationOutcome,
    CitationVerificationSummary,
    CitationVerifier,
)
from core.verification.claims.extractor import (
    ClaimExtractor,
    ExtractedClaim,
    ExtractionResult,
)
from core.verification.claims.verifier import ClaimVerifier

__all__ = [
    "CitationOutcome",
    "CitationVerificationSummary",
    "CitationVerifier",
    "ClaimExtractor",
    "ClaimVerifier",
    "ExtractedClaim",
    "ExtractionResult",
]