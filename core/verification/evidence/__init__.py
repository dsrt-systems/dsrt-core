"""
Evidence & Claims Management (C6 §14-19).

Persistent storage, provenance tracking, and claim lifecycle management
for the verification fabric.
"""

from core.verification.evidence.store import EvidenceStore
from core.verification.evidence.provenance import EvidenceProvenanceTracker

__all__ = ["EvidenceStore", "EvidenceProvenanceTracker"]