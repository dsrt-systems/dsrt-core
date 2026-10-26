# C10 — Unified Execution & Comparison Engine

## Phase C10.1 & C10.2: Contracts and Core Controller
Delivered foundational schemas, ORM models, Repositories, Admission Gates, Idempotency tracking, and the main `ExecutionController`.

## Phase C10.3: Direct Execution Runtime
Delivered the baseline Direct Execution Protocol.
1. **`DirectContextBinder`**: Unifies configuration and payloads cleanly.
2. **`DirectExecutionAdapter`**: Protects the C10 runtime from C2 API failures, guaranteeing resilient C10 execution traces.
3. **`StepRunner`**: Integrates perfectly with `ExecutionStepRepository`, capturing metrics (tokens, duration, estimated cost) and durably persisting state transitions (`StepKind`, `StepStatus`).
4. **`DirectRuntime`**: Defines the two-step Direct protocol (Bind Context -> Invoke Model), recording metrics back into the `ExecutionTraceORM`.
5. **`DirectExecutionProtocol`**: Concrete implementation of `BaseExecutionProtocol` ready for the `ProtocolRegistry`.

### Implementation Notes:
- Fully aligned with `schemas.domain.enums` and `schemas.domain.execution_c10`.
- Implements correct SQLAlchemy `AsyncSession` constructor injection standard.
- Tests isolated with `AsyncMock` to ensure stability across build environments without database setup hurdles.

## Phase C10.4: Amplification Runtime
Delivered the dynamic, multi-strategy `AmplifiedExecutionProtocol`.
1. **`AmplifiedSubsystemAdapter`**: The secure integration bridge connecting C10 to the C1-C9 subsystems (Context, Orchestration, Tools, Verification) without violating encapsulation.
2. **`AmplificationStrategy` Framework**: Implemented the 5 DSRT-mandated core strategies (`PLANNING`, `CONTEXT_RETRIEVAL`, `TOOL_GROUNDED`, `VERIFICATION`, `REPAIR`). 
3. **`AmplifiedPipeline`**: Dynamically orchestrates the sequence of strategies based on the configuration, securely passing a shared `state` dictionary between pipeline boundaries.
4. **`AmplifiedRuntime`**: The main execution loop wrapping the pipeline and recording final trace metrics (cost, duration, steps) to the database using exact C10 schemas.

## C10.4 Fix Note — ORM/Repository Alignment
C10.4 verification exposed a real production defect from C10.2 repositories:

| Domain / Repo API | Live ORM column |
|---|---|
| `trace_id` | `execution_trace_id` |
| `step_number` | `step_index` |
| `input_data` / `output_data` | `inputs_ref` / `outputs_ref` |
| `tokens_used` | `input_tokens` + `output_tokens` |
| `total_cost` | `total_cost_usd` |
| `total_tokens` | `total_input_tokens` + `total_output_tokens` |
| `duration_ms` (trace) | `total_duration_ms` |
| `total_steps` | `step_count` |

**Fix applied properly (not patched):**
- `ExecutionStepRepository` and `ExecutionTraceRepository` now map domain API → ORM columns correctly.
- `ExecutionTrace` / `ExecutionStep` Pydantic schemas accept ORM objects via explicit field mappers.
- `create_trace` loads required identity fields (`agent_slug`, `agent_version_id`, `model_fingerprint_id`) from `ExecutionConfigurationORM`.
- No invalid kwargs are passed to SQLAlchemy ORM constructors.


---

## C10.5 — Paired Experiment Controller

**Status:** ✅ Complete  
**Date:** 2025-01-XX

### Purpose
The Paired Experiment Controller coordinates controlled comparison experiments where the same task executes through multiple configurations under fair, isolated conditions. This powers Comparison Mode (the spec's "War Mode" equivalent).

### Architecture
```
ExperimentRequest (≥2 configurations)
│
▼
ExperimentController
├── validate (permissions, budget, executor availability)
├── TaskSnapshotBuilder → frozen TaskSnapshot (SHA-256 integrity)
├── RunIsolationManager → N isolated IsolatedRunContext objects
├── RunCoordinator → sequential/concurrent execution
└── ExperimentResult (aggregated outcomes)

```

### Components

| File | Class | Responsibility |
|---|---|---|
| `core/execution/experiments/snapshot.py` | `TaskSnapshot`, `TaskSnapshotBuilder` | Immutable capture of task, context, model, environment, evaluation state. SHA-256 content hash for tamper detection. |
| `core/execution/experiments/isolation.py` | `RunIsolationManager`, `IsolatedRunContext` | Creates isolated execution contexts per run with separate IDs, trace IDs, cost accumulators, artifact namespaces. Verifies snapshot integrity before each context creation. |
| `core/execution/experiments/coordinator.py` | `RunCoordinator`, `RunOutcome`, `RunStatus`, `RunExecutor` | Orchestrates sequential or concurrent execution of multiple runs. Handles per-run failures, experiment budget enforcement, cancellation propagation. |
| `core/execution/experiments/experiment_controller.py` | `ExperimentController`, `ExperimentRequest`, `ExperimentResult`, `ExperimentConfiguration`, `ExperimentBudget`, `ExperimentState` | Top-level lifecycle: validate → snapshot → isolate → execute → collect. State machine with valid transitions. |
| `core/execution/protocols/paired.py` | `PairedComparisonProtocol` | Adapts ExperimentController as a `BaseExecutionProtocol` for the protocol registry. |

### Key Design Decisions

1. **Configurations are a list, not a fixed pair.** The contract supports 2+ configurations from the start, enabling multi-model, multi-strategy, and multi-agent experiments.
2. **Snapshot integrity.** Every snapshot is frozen with a SHA-256 hash. The isolation manager re-verifies integrity before creating each run context.
3. **Run isolation.** Each run gets independent execution_id, trace_id, cost accumulator, and artifact namespace. Side-effects from one run cannot contaminate another.
4. **Budget enforcement at two levels.** Per-run budgets in `IsolatedRunContext` and experiment-level budgets in `RunCoordinator`.
5. **Failure containment.** One failed run does not abort the experiment; the controller reports PARTIALLY_COMPLETED.
6. **Executor contract.** Protocol runtimes implement `RunExecutor` so the coordinator executes them uniformly without knowing their internals.

### State Machine

```

CREATED → VALIDATING → SNAPSHOT_CREATED → RUNS_CREATED → EXECUTING → COMPLETED
→ PARTIALLY_COMPLETED
→ FAILED
→ CANCELLED
(CANCELLED is reachable from any non-terminal state)

```



### Tests
`tests/test_c10_paired_experiment.py` — 20 tests covering:
- Snapshot build, freeze, integrity, determinism, mutation detection
- Isolation context creation, unfrozen/tampered rejection, budget tracking
- Coordinator sequential execution, one-fails, cancellation, budget enforcement, missing executor, executor exception
- State machine valid/invalid transitions
- ExperimentController full lifecycle, partial failure, all-fail, validation rules, multi-config
- PairedComparisonProtocol validate/prepare/execute/finalize


---

## C10.6 — Model Resolution & Profile Registry

**Status:** ✅ Complete  
**Date:** 2025-01-XX

### Purpose
C10.6 establishes canonical model identity and a three-layer profile
registry. Every execution now resolves to a verified connection, builds
a cryptographic fingerprint, and attaches evidence that is correctly
attributed as fresh or reused.

### Components

| File | Class | Responsibility |
|---|---|---|
| `core/execution/models/fingerprint.py` | `ModelFingerprint`, `ModelFingerprinter`, `FingerprintField` | SHA-256 canonical identity across provider, model_id, snapshot, endpoint, inference_cfg, quantization, hardware, tool_capabilities. Unknown fields recorded explicitly. |
| `core/execution/models/resolver.py` | `ModelResolver`, `ResolvedModelConnection`, `ModelGatewayAdapter`, `ConnectionSource`, resolver errors | Resolves selection → verified connection + fingerprint + capability snapshot. Credentials never leave C2 vault. |
| `core/execution/models/profiles.py` | `SharedModelProfile`, `ConnectionProfile`, `ExecutionProfile`, `ProfileRegistry`, service classes, `InMemoryProfileStore`, `ProfileStore` protocol | Three profile layers; registry enforces reused-evidence flagging. |
| `core/execution/models/profiling.py` | `TieredProfilingOrchestrator`, `ProfilingTier`, `ProfilingRequest`, `ProfilingDecision`, `ProfilingResult`, `ProfilingTierResult` | 5-tier (0–4) orchestration. Tiers ≥2 require explicit user authorization. Tier 2–4 await C8/C11 probe registries. |

### Key Rules Enforced

1. **No model is identified by display name alone.** A fingerprint is required for every attribution.
2. **Unknown fingerprint fields are recorded, not fabricated.**
3. **Credentials never appear in profiles, fingerprints, or traces.**
4. **Reused shared evidence is explicitly flagged** via `is_reused_evidence` so UI cannot misrepresent it as a fresh test on the user's own connection.
5. **Expensive profiling tiers require explicit user authorization.** The planner returns `requires_user_authorization` so the UI can prompt before spending tokens.
6. **Tiers 2–4 return `SKIPPED` with an explanatory reason** until probe registries are wired up — never a false success.

### Three Profile Layers

| Layer | Scope | Lifetime | Keyed by |
|---|---|---|---|
| `SharedModelProfile` | Global per fingerprint | Long-lived | `fingerprint_hash` |
| `ConnectionProfile` | Per workspace+connection | Lifetime of connection | `(workspace_id, connection_id)` |
| `ExecutionProfile` | Observed behavior | Grows with every execution | `(workspace_id, connection_id, fingerprint_hash)` |

### Profiling Tiers

| Tier | Name | Cost | Requires Auth |
|---|---|---|---|
| 0 | IDENTIFY | 0 (metadata only) | No |
| 1 | VERIFY | ~0 (reachability only) | No |
| 2 | DOMAIN_PROBE | token-spending | **Yes** |
| 3 | DEEP_CAPABILITY | token-spending | **Yes** |
| 4 | FRESH_EXPERIMENT | token-spending | **Yes** |

### Tests
`tests/test_c10_model_resolution.py` — 30+ tests covering:
- Fingerprint determinism, mismatch detection, unknown-field recording, display name, tool-capability order invariance
- Resolver happy path, missing connection, unreachable, capability mismatch, skipped reachability, unknown source, missing provider, metadata-fetch failure
- Shared/Connection/Execution profile CRUD, aggregation, error tracking
- **Critical:** fresh vs reused evidence flagging
- Orchestrator planning (tiers, authorization), execution (tier 0 only, tier 0→1, reuse detection, unauthorized marking, failure propagation)

---

## C10.7 — Evaluation Engine

**Status:** ✅ Complete  
**Date:** 2025-01-XX

### Purpose
Unified evaluation interface for Direct and Amplified execution outputs.
Consumes C8 evaluator infrastructure through adapters; does not replace it.

### Components

| File | Class | Responsibility |
|---|---|---|
| `core/execution/evaluation/contracts.py` | `EvaluationCategory`, `ScoreKind`, `EvaluationInput`, `NormalizedMetric`, `EvaluationFinding`, `EvaluationLimitation`, `EvaluatorRef` | Shared contracts. `ScoreKind.QUALITATIVE` forbids numeric values. |
| `core/execution/evaluation/adapters.py` | `BenchmarkRegistryAdapter`, `NullBenchmarkRegistryAdapter`, `SuiteDescriptor`, `EvaluatorDescriptor` | C8 registry contract + safe null adapter. |
| `core/execution/evaluation/methods.py` | `DeterministicEvaluator`, `EvidenceEvaluator`, `RubricEvaluator`, `RubricDefinition` | Three evaluation methods. Rubric numeric mapping is opt-in only. |
| `core/execution/evaluation/normalizer.py` | `MetricNormalizer` | Merges multi-method metrics; strips illegal qualitative numerics; prefers higher confidence then DETERMINISTIC > EVIDENCE > RUBRIC. |
| `core/execution/evaluation/service.py` | `EvaluationEngine`, `EvaluationRequest`, `EvaluationServiceResult` | Top-level orchestration, overall-score policy, human-review flags, C8 suite resolution. |

### Evaluation Categories
`TASK_SUCCESS` · `CORRECTNESS` · `COMPLETENESS` · `CONSTRAINT_ADHERENCE` · `EVIDENCE_QUALITY` · `TOOL_EXECUTION` · `RELIABILITY` · `ARTIFACT_QUALITY` · `SAFETY_AND_POLICY`

### Three Methods

| Method | Produces numbers when | Never does |
|---|---|---|
| DETERMINISTIC | status, match, schema, ratios, tool success | semantic quality guesses |
| EVIDENCE | counts, tool-backed ratios, linkage ratios | overall evidence float |
| RUBRIC | only if `allow_numeric_mapping=True` | silent ordinal→float conversion |

### Overall Score Policy
An `overall_score` float is emitted **only** when high-confidence DETERMINISTIC NUMERIC_BOUNDED metrics exist for task success / correctness / completeness / reliability. Otherwise `overall_score=None` and `overall_qualitative` carries the summary. Limitations are always recorded when data is missing.

### Critical Rule Enforcement
1. `ScoreKind.QUALITATIVE` metrics may not carry a numeric `value` (normalizer strips them).
2. Default rubric never maps ordinals to floats.
3. Rubric-only / evidence-only evaluations produce `overall_score=None`.
4. Safety metric is explicitly `not_reviewed` — never a fake pass.
5. Every evaluation records evaluator ID/version, method, findings, limitations, confidence, timestamp.

### Tests
`tests/test_c10_evaluation_engine.py` — 30+ tests covering all methods, normalizer, engine composition, C8 suite hook, and the critical no-fabricated-score rule.


---

## C10.8 — Economics & Cost Ledger

**Status:** ✅ Complete  
**Date:** 2025-01-XX

### Purpose
Authoritative cost accounting for every Direct, Amplified, and Experiment
execution. Separates actual / estimated / unavailable costs, enforces
multi-level budgets before expensive operations, and computes savings
only when quality is comparable.

### Components

| File | Class | Responsibility |
|---|---|---|
| `core/execution/economics/contracts.py` | `CostEntry`, `CostCategory`, `CostAvailability`, `CostBreakdown`, `BudgetDefinition`, `BudgetCheckResult`, `EconomicsSummary` | Shared economics schemas |
| `core/execution/economics/pricing.py` | `PricingSnapshot`, `ModelPrice`, `ToolPrice`, `PricingDirectory` | Immutable versioned price tables; estimate model/tool/env cost |
| `core/execution/economics/ledger.py` | `CostLedger` | Append-only attributable journal; idempotency; actual/estimated/unavailable breakdown |
| `core/execution/economics/budget.py` | `BudgetEnforcer`, `BudgetExceededError` | Pre-op gates: allow/warn/deny; per-call and repair caps; multi-scope |
| `core/execution/economics/calculations.py` | `CostCalculator`, `CostComparisonResult` | Cost/attempt, cost/success, fair savings with quality gate |
| `core/execution/economics/service.py` | `EconomicsEngine`, `RecordUsageRequest`, `EconomicsReport` | Facade for runtimes: authorize → record → report → compare |

### Cost Categories
`MODEL_INFERENCE` · `HOSTED_INFERENCE` · `PLANNING` · `RETRIEVAL` · `TOOLS` · `ENVIRONMENT` · `VERIFICATION` · `RECOVERY` · `INFRASTRUCTURE` · `OTHER`

### Availability
| Level | Meaning |
|---|---|
| ACTUAL | Provider-reported or precisely metered dollar amount |
| ESTIMATED | pricing_snapshot × usage |
| UNAVAILABLE | Operation known to have occurred; no amount — tracked, excluded from known totals |

### Budget Enforcement Points
Before run start · model invoke · tool call · retry/repair · escalation · during long runs. DENY raises `BudgetExceededError`.

### Savings Rule

cost_savings = 1 - C_candidate / C_baseline
Marked `valid=True` only when quality scores are present and candidate quality meets threshold. Otherwise savings may be computed for inspection but must not be claimed.

### Idempotency
Identical `idempotency_key` returns the original entry — no double-charge on worker retry.

### Tests
`tests/test_c10_economics.py` — 35+ tests: pricing, ledger, budget, calculator, engine E2E, quality-gated comparison, experiment budget.

## Sub-phase C10.9 — Trace, Event & Artifact Integration

### Implemented Architecture
1. **Trace Collector & Redactor (`core/execution/observability/traces.py`)**:
   - Spans record execution inputs, outputs, tokens, costs, and millisecond durations.
   - `Redactor` automatically sanitizes API keys (`sk-*`), Bearer tokens, passwords, and sensitive dictionary keys across all trace data.

2. **Event Integration & Publisher (`core/execution/observability/events.py`)**:
   - `EventPublisher` defines standard event types (`C10EventType`) across execution and experiment lifecycles.
   - Implements outbox pattern buffering and event subscriptions.

3. **Artifact Manager (`core/execution/observability/artifacts.py`)**:
   - Persists execution deliverables (code, JSON, text, patches) with SHA-256 integrity hashes.
   - Multi-tenant workspace validation blocks unauthorized cross-workspace artifact reads.

4. **Observability Service (`core/execution/observability/service.py`)**:
   - Unified facade coordinating step trace lifecycle, event notifications, and artifact creation.

## Sub-phase C10.10 — Comparison & Results Engine + System Integration

### Comparison Engine (`core/execution/comparison/`)
- **contracts.py** — `ConfigurationRunEvidence`, `DimensionComparison`, `ComparisonRequest`, `ComparisonResult`, `ComparisonOutcomeKind`.
- **metrics.py** — Dimension calculators: quality, completion, correctness, reliability, cost, latency, verification, recovery.
- **engine.py** — Fair multi-config comparison; **no universal winner**; cost savings claimable only when quality gates pass.
- **reports.py** — JSON + Markdown report builders (`universal_winner` always `null`).
- **service.py** — Application facade + in-memory comparison history.

### Outcome kinds
- `candidate_better_quality_lower_cost`
- `candidate_better_quality_higher_cost`
- `baseline_cheaper_comparable_quality`
- `baseline_better_quality`
- `all_failed` / `partial` / `inconclusive` / `invalid` / `mixed`

### Integration (`core/execution/integration/`)
- Protocol-agnostic `ExecutionRequest` / `ExecutionResult`.
- `ExecutionProtocol` contract (validate / prepare / execute / finalize).
- `RuntimeDependencies` ports for C1–C9 (agents, models, context, tools, world, verification, benchmarks, events, artifacts, state).
- `UnifiedExecutionEngine` — single facade for direct, amplified, and paired protocols; wires evaluation, economics, observability, comparison.

### HTTP API (`core/execution/api/`)
- `POST/GET /api/v1/executions`, cancel, status
- `POST/GET /api/v1/experiments`, comparison sub-resource
- Evaluation & cost read routes under `/api/v1/executions/{id}/evaluation|cost`

### Tests
`tests/test_c10_comparison_integration.py` — comparison matrix, savings guards, multi-config rankings, unified engine paired/direct/cancel/validation.