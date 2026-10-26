# DSRT Core — Phase C9: Intelligence Routing Fabric

## Mission

C9 transforms DSRT from a system that *measures* intelligence (C8) into one that *deploys* intelligence optimally. Given a task, agent, world, policy, budget, and quality level, the Intelligence Routing Fabric determines the complete execution configuration.

## Architecture
USER TASK → REQUIREMENTS → CAPABILITIES → CANDIDATES → POLICIES → EVIDENCE → ROUTE → EXECUTE → OBSERVE → ADAPT


A **Route** is not merely a model selection. It is a full configuration: agent, model, provider, world, tools, verification policy, execution strategy, and fallback chain.

## Core Principles

1. **No hardcoded routing.** All decisions flow through capability matching, policy filtering, and evidence evaluation.
2. **Hard constraints vs soft preferences.** Security, permissions, and required capabilities are binary gates. Quality, latency, and cost are graded preferences.
3. **Evidence over declarations.** Arena-observed performance takes precedence over self-declared capabilities.
4. **Explainability.** Every routing decision retains per-dimension evidence, rejection reasons, and policy references.
5. **Immutability.** Routes, evidence, and requirements are frozen dataclasses — tamper-proof after creation.

## Components

| Module | Purpose |
|--------|---------|
| `contracts.py` | 15+ dataclasses: Route, RouteCandidate, RouteDecision, RoutingPolicy, TaskRequirements, RoutingEvidence, etc. |
| `enums.py` | TaskDomain, QualityLevel, RoutingStatus, EligibilityStatus, EvidenceSourceType, ExecutionStage, etc. |
| `requirements/extractor.py` | Structured requirement extraction from task descriptions |
| `analyzer/classifier.py` | Task classification into domains (RESEARCH, CODING, DATA_ANALYSIS, etc.) |
| `capabilities/matcher.py` | Agent/model capability matching against requirements |
| `candidates/generator.py` | Broad candidate generation from agent × model × world combinations |
| `policies/engine.py` | Hard constraint filtering + soft preference scoring |
| `policies/constraints.py` | RoutingConstraints with allowed/denied lists |
| `policies/preferences.py` | RoutingPreferences for quality/cost/latency tradeoffs |
| `profiles/registry.py` | Named routing profiles (FAST, QUALITY, COST_CONTROLLED, etc.) |
| `evidence/adapter.py` | Arena evidence adapter |
| `evidence/aggregator.py` | Multi-source evidence aggregation with confidence weighting |
| `evidence/freshness.py` | Evidence staleness detection and decay |
| `selector/router.py` | IntelligenceRouter — central routing decision engine |
| `selector/evaluator.py` | Multi-dimensional route evaluation |
| `selector/selector.py` | Final route selection from evaluated candidates |
| `selector/explainer.py` | Human-readable routing decision explanations |
| `adaptive/controller.py` | Mid-execution route re-evaluation and switching |
| `adaptive/stage_router.py` | Per-stage model routing (PLANNING, RETRIEVAL, SYNTHESIS, etc.) |
| `fallback/engine.py` | Fallback policy execution on route failure |
| `escalation/engine.py` | Human escalation for critical failures |
| `health/tracker.py` | Provider health monitoring (AVAILABLE, DEGRADED, RATE_LIMITED, etc.) |
| `cache/manager.py` | Deterministic route caching with invalidation |
| `events.py` | 13 routing event types for full audit trail |
| `integrations/` | Cross-phase bridges to Arena, Orchestration, Verification, Kernel |

## Security Model

- All core dataclasses are `frozen=True` — immutable after construction
- Policy constraints enforce model/agent/provider allowlists and denylists
- Security requirements (sandbox, privilege level, external actions, domain restrictions) are enforced at the routing layer
- Evidence cannot be inflated or tampered with post-creation
- Route decisions retain full audit trails with rejection reasons

## Integration Points

- **C5 Orchestration:** `OrchestrationRoutingHook` provides replan decisions with configurable thresholds
- **C6 Verification:** `VerificationRoutingHook` maps quality levels to verification check sets
- **C8 Arena:** `ArenaEvidenceBridge` converts Arena run metrics into routing evidence
- **C5 Kernel:** `KernelRoutingHook` integrates route caching with execution lifecycle

## Test Coverage

| Test Suite | Tests | Coverage |
|-----------|-------|----------|
| Contracts & Enums | 128 | All dataclasses, enums, validation |
| Models | 66 | Capability profiles, proficiency |
| Requirements | 50 | Extraction, classification |
| Candidates | 48 | Generation, eligibility |
| Evidence | 47 | Aggregation, freshness, adapter |
| Selector | 34 | Router, evaluator, explainer |
| Adaptive | 31 | Controller, stage routing |
| Health & Cache | 26 | Provider health, cache lifecycle |
| SDK & Events | 20 | SDK interface, event emission |
| Integration | 52 | Cross-phase bridges, golden scenario |
| Security | 28 | Immutability, policy, evidence integrity |
| Benchmarks | 15 | Accuracy, latency, compliance, reproducibility |
| **Total** | **545** | |

## Definition of Done

C9 is complete when DSRT can:
- **Understand** task requirements, capabilities, and constraints
- **Select** agents, models, worlds, tools, and execution strategies
- **Reason from evidence** with sample size and freshness awareness
- **Enforce** organization policies, security, budget, and latency constraints
- **Adapt** mid-execution with fallback, model switching, and replanning
- **Explain** every routing decision with full audit trail
