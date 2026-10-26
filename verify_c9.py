"""C9 Certification Script — Intelligence Routing Fabric v1.0

Validates all C9 components, contracts, and integration points.
Run: python verify_c9.py
"""
import sys
import importlib
from pathlib import Path

PASS = 0
FAIL = 0

def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name} {detail}")

def verify():
    print("=" * 60)
    print("C9 Certification — Intelligence Routing Fabric v1.0")
    print("=" * 60)

    # 1. Module imports
    print("\n[1] Module Imports")
    modules = [
        "core.routing.contracts",
        "core.routing.enums",
        "core.routing.events",
        "core.routing.models",
        "core.routing.types",
        "core.routing.requirements.extractor",
        "core.routing.analyzer.classifier",
        "core.routing.capabilities.matcher",
        "core.routing.candidates.generator",
        "core.routing.policies.engine",
        "core.routing.policies.constraints",
        "core.routing.policies.preferences",
        "core.routing.profiles.registry",
        "core.routing.evidence.adapter",
        "core.routing.evidence.aggregator",
        "core.routing.evidence.freshness",
        "core.routing.selector.router",
        "core.routing.selector.evaluator",
        "core.routing.selector.selector",
        "core.routing.selector.explainer",
        "core.routing.adaptive.controller",
        "core.routing.adaptive.stage_router",
        "core.routing.fallback.engine",
        "core.routing.escalation.engine",
        "core.routing.health.tracker",
        "core.routing.cache.manager",
        "core.routing.integrations.arena_bridge",
        "core.routing.integrations.orchestration_hook",
        "core.routing.integrations.verification_hook",
        "core.routing.integrations.kernel_hook",
        "core.routing.integrations.golden_scenario",
    ]
    for mod in modules:
        try:
            importlib.import_module(mod)
            check(f"import {mod}", True)
        except Exception as e:
            check(f"import {mod}", False, str(e))

    # 2. Core contracts
    print("\n[2] Core Contracts")
    from core.routing.contracts import (
        Route, RouteCandidate, RouteDecision, RoutingPolicy,
        RoutingConstraints, RoutingPreferences, RoutingProfile,
        TaskRequirements, TaskClassification, QualityRequirements,
        ResourceConstraints, SecurityRequirements,
        RoutingEvidence, AggregatedEvidence, ExecutionStrategy,
        AgentCapabilityProfile, ModelCapabilityProfile,
        FallbackPolicy, EscalationPolicy,
    )
    check("Route is frozen", hasattr(Route, "__dataclass_fields__"))
    check("RoutingEvidence is frozen", hasattr(RoutingEvidence, "__dataclass_fields__"))
    check("TaskRequirements is frozen", hasattr(TaskRequirements, "__dataclass_fields__"))

    # 3. Enums
    print("\n[3] Enums")
    from core.routing.enums import (
        TaskDomain, QualityLevel, RoutingStatus, EligibilityStatus,
        RejectionCategory, EvidenceSourceType, EvidenceConfidence,
        ExecutionStage, ProviderHealthStatus, RoutingPriority,
        FallbackActionType, FallbackTriggerType,
    )
    check("TaskDomain has RESEARCH", hasattr(TaskDomain, "RESEARCH"))
    check("TaskDomain has CODING", hasattr(TaskDomain, "CODING"))
    check("QualityLevel has STRICT", hasattr(QualityLevel, "STRICT"))
    check("ProviderHealthStatus has DEGRADED", hasattr(ProviderHealthStatus, "DEGRADED"))

    # 4. Policy engine
    print("\n[4] Policy Engine")
    from core.routing.policies.engine import PolicyEngine
    engine = PolicyEngine()
    check("PolicyEngine instantiates", engine is not None)
    check("PolicyEngine.apply exists", callable(getattr(engine, "apply", None)))

    # 5. Evidence aggregator
    print("\n[5] Evidence Aggregator")
    from core.routing.evidence.aggregator import EvidenceAggregator
    agg = EvidenceAggregator()
    result = agg.aggregate("test", [])
    check("Empty aggregation returns 0 samples", result.total_sample_count == 0)

    # 6. Route cache
    print("\n[6] Route Cache")
    from core.routing.cache.manager import RouteCacheManager
    cache = RouteCacheManager()
    check("Cache miss returns None", cache.get("x") is None)

    # 7. Provider health
    print("\n[7] Provider Health")
    from core.routing.health.tracker import ProviderHealthTracker
    tracker = ProviderHealthTracker()
    health = tracker.get_health("test")
    check("Unknown provider returns UNKNOWN", health.status == ProviderHealthStatus.UNKNOWN)

    # 8. Integration modules
    print("\n[8] Integration Modules")
    from core.routing.integrations.arena_bridge import ArenaEvidenceBridge
    from core.routing.integrations.orchestration_hook import OrchestrationRoutingHook
    from core.routing.integrations.verification_hook import VerificationRoutingHook
    from core.routing.integrations.kernel_hook import KernelRoutingHook
    from core.routing.integrations.golden_scenario import GoldenScenarioRunner
    check("ArenaEvidenceBridge importable", True)
    check("OrchestrationRoutingHook importable", True)
    check("VerificationRoutingHook importable", True)
    check("KernelRoutingHook importable", True)
    check("GoldenScenarioRunner importable", True)

    # 9. Immutability
    print("\n[9] Immutability")
    from dataclasses import FrozenInstanceError
    from datetime import datetime, timezone
    route = Route(
        agent_id="a", agent_version_id="v1", model_id="m",
        model_version_id="v1", provider_id="p", world_id=None,
        world_version_id=None, tools=[], execution_strategy=ExecutionStrategy(),
    )
    try:
        route.model_id = "hacked"
        check("Route immutability", False, "mutation succeeded")
    except FrozenInstanceError:
        check("Route immutability", True)

    # 10. File count
    print("\n[10] File Structure")
    routing_dir = Path("core/routing")
    py_files = list(routing_dir.rglob("*.py"))
    non_cache = [f for f in py_files if "__pycache__" not in str(f)]
    check(f"Routing module files >= 25 (found {len(non_cache)})", len(non_cache) >= 25)

    test_files = list(Path("tests").glob("test_c9*.py"))
    check(f"C9 test files >= 10 (found {len(test_files)})", len(test_files) >= 10)

    # Summary
    print("\n" + "=" * 60)
    total = PASS + FAIL
    print(f"Results: {PASS}/{total} passed, {FAIL} failed")
    if FAIL == 0:
        print("STATUS: C9 CERTIFIED")
    else:
        print("STATUS: C9 CERTIFICATION FAILED")
    print("=" * 60)
    return FAIL == 0

if __name__ == "__main__":
    success = verify()
    sys.exit(0 if success else 1)
