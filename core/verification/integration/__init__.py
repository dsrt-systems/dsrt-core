"""
C6 ↔ C5 Integration Hooks (C6 §56-58).

Bridges the Verification Fabric to the Orchestration Fabric.
These hooks are called by the C5 orchestrator at key points
in the execution lifecycle.

Integration Points:
  1. Node Verification Hook — after node execution, before COMPLETED
  2. Scheduler Hook — verification as dependency signal
  3. Replanner Hook — verification failures trigger replanning

C6 does NOT modify C5 code. C5 calls these hooks.
"""

from core.verification.integration.node_hook import NodeVerificationHook
from core.verification.integration.scheduler_hook import VerificationSchedulerHook
from core.verification.integration.replan_hook import VerificationReplanHook

__all__ = [
    "NodeVerificationHook",
    "VerificationReplanHook",
    "VerificationSchedulerHook",
]