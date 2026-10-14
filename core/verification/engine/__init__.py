"""
Verification Engine (C6 §7-9, §12-13).

The central orchestrator for independent verification.
Receives requests, resolves policies, runs checks, aggregates results.
"""

from core.verification.engine.engine import VerificationEngine
from core.verification.engine.lifecycle import VerificationLifecycleManager
from core.verification.engine.request import VerificationRequestProcessor

__all__ = [
    "VerificationEngine",
    "VerificationLifecycleManager",
    "VerificationRequestProcessor",
]