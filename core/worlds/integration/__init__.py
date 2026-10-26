"""
C7 Integration with C5 Orchestration and C6 Verification (C7 §35, §44, §64).

Provides hooks that C5 and C6 call to interact with the World Runtime:
  - WorldResolver: C5 orchestrator selects and provisions worlds for nodes
  - WorldVerificationHook: C6 verifies world state after agent actions
"""

from core.worlds.integration.resolver import WorldResolver
from core.worlds.integration.verification_hook import WorldVerificationHook

__all__ = ["WorldResolver", "WorldVerificationHook"]