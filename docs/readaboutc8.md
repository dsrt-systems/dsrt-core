# DSRT Core — Phase C8 Arena & Evaluation Fabric v1.0

**Status:** Certified Complete (C8.1 → C8.11)
**Core Version:** `1.0.0`
**Database:** Supabase (Managed PostgreSQL 16 + `dsrt` schema)
**New Tables:** 12 (benchmarks, task_suites, task_definitions, task_instances, experiments, arena_runs, trajectories, trajectory_events, evaluators, metric_results, performance_profiles, regressions)

---

## 1. Phase C8 Objective

Build the controlled experimentation and evaluation system that measures intelligence across MODEL × AGENT × WORLD × TASK configurations.

> **C8 answers: "How do we measure what happened, why, and how reliably?"**

The Arena is NOT a leaderboard. It is a measurement infrastructure that preserves multi-dimensional evidence.

---

## 2. Sub-Phase Summary

| Sub-Phase | Component | Deliverables |
|---|---|---|
| C8.1 | Schemas | 7 enums, 15 domain schemas, 8 API schemas, 11 ID prefixes |
| C8.2 | Database | 12 ORM models with relationships and indexes |
| C8.3 | Registry | BenchmarkRegistry, TaskRegistry, hidden state, randomization |
| C8.4 | Experiment/Run | ExperimentManager, ArenaRunManager, 11-state lifecycle |
| C8.5 | Trajectory | TrajectoryBuilder, TrajectoryStore, event normalization |
| C8.6 | Evaluators | DeterministicEvaluator, TrajectoryEvaluator, isolation |
| C8.7 | Metrics | MetricComputer, PerformanceProfileBuilder, cost separation |
| C8.8 | Regression | RegressionDetector, CapabilityProfiler, FailureAnalyzer |
| C8.9 | SDK/API | ArenaSDK (read-only), 10 REST endpoints |
| C8.10 | Integration | C5 Orchestrator hook, C6 Verification hook |
| C8.11 | Certification | 50+ tests, verify_c8.py, readaboutc8.md |

---

## 3. Core Principles

1. **No single score** — Performance is multi-dimensional (correctness, completeness, reliability, recovery, cost, latency, safety)
2. **Evidence-first** — Every metric points to evidence; no score without provenance
3. **Evaluator isolation** — Agents cannot evaluate themselves (C8 §57)
4. **Trajectory > Answer** — Process matters as much as outcome (C8 §18)
5. **Benchmark ≠ Experiment ≠ Run** — Three distinct concepts (C8 §5)
6. **Configuration fingerprint** — Every run is reproducible (C8 §43)
7. **Variance preserved** — Never hide statistical uncertainty (C8 §36)
8. **Deterministic first** — Code-based checks before model-based (C8 §25)

---

## 4. Architecture
```
BENCHMARK → EXPERIMENT → RUN → EXECUTION
↓
TRAJECTORY
↓
EVALUATION
├── Deterministic (Layer 1)
├── Trajectory (Layer 2)
└── Resources (Layer 3)
↓
METRICS
↓
PERFORMANCE PROFILE
├── correctness: 0.91
├── completeness: 0.88
├── reliability: 0.94
├── recovery: 0.79
├── tool_efficiency: 0.82
├── latency: 184s
└── cost: $0.61
```


---

## 5. REST API

```
POST /api/v1/benchmarks Create benchmark
GET /api/v1/benchmarks List benchmarks
GET /api/v1/benchmarks/{id} Get benchmark
POST /api/v1/experiments Create experiment
GET /api/v1/experiments/{id} Get experiment
GET /api/v1/arena/runs/{id} Get Arena run
GET /api/v1/arena/runs/{id}/trajectory Get trajectory
GET /api/v1/arena/runs/{id}/metrics Get metrics
GET /api/v1/arena/regressions Get regressions
GET /api/v1/arena/capabilities Get capability profile

```


---

## 6. Agent SDK

```python
# Record metrics (existing C1 SDK)
await sdk.benchmark.record("research.questions", value=8, total=10)

# Read past Arena results (C8 — read-only)
result = await sdk.arena.get_last_result("research_v1")
scores = await sdk.arena.get_capability_scores()
```
Agents cannot modify evaluations, access hidden state, or alter trajectories.

7. Run Instructions
PowerShell

python scripts/verify_c8.py
python -m pytest tests/unit/test_c8_arena.py -v
python main.p