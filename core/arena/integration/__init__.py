"""
C8 Integration with C5, C6, C7 (C8 §66-67).

Hooks that connect the Arena evaluation fabric to:
  - C5 Orchestration (trajectory capture from execution events)
  - C6 Verification (verification results as evaluation inputs)
  - C7 Worlds (world provisioning for Arena runs)
"""

from core.arena.integration.orchestrator_hook import ArenaOrchestratorHook
from core.arena.integration.verification_hook import ArenaVerificationHook

__all__ = ["ArenaOrchestratorHook", "ArenaVerificationHook"]