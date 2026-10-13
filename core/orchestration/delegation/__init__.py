"""
Agent Delegation Runtime (C5 §16-18, §41, §81-84).

Capability-based agent-to-agent delegation with:
  - Permission inheritance (child ⊆ parent)
  - Budget propagation (child ≤ parent remaining)
  - Depth limits (prevent runaway recursion)
  - Agent resolution by capability
"""

from core.orchestration.delegation.delegation import (
    DelegationManager,
    DelegationRequest,
    DelegationResult,
)

__all__ = ["DelegationManager", "DelegationRequest", "DelegationResult"]