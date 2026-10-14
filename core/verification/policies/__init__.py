"""
Verification Policy Management (C6 §10, §45-46).

Policy registry, resolution, and evaluation for the verification fabric.
"""

from core.verification.policies.policy import VerificationPolicyManager
from core.verification.policies.registry import PolicyRegistry

__all__ = ["PolicyRegistry", "VerificationPolicyManager"]