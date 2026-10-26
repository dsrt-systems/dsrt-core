"""C9.10 - Cross-Phase Integration Bridges."""
from core.routing.integrations.arena_bridge import ArenaEvidenceBridge
from core.routing.integrations.orchestration_hook import OrchestrationRoutingHook
from core.routing.integrations.verification_hook import VerificationRoutingHook, VerificationConfig
from core.routing.integrations.kernel_hook import KernelRoutingHook
from core.routing.integrations.golden_scenario import GoldenScenarioRunner, GoldenScenarioResult

__all__ = [
    "ArenaEvidenceBridge",
    "OrchestrationRoutingHook",
    "VerificationRoutingHook",
    "VerificationConfig",
    "KernelRoutingHook",
    "GoldenScenarioRunner",
    "GoldenScenarioResult",
]
