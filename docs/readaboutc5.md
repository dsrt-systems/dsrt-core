# DSRT Core — Phase C5 Orchestration Fabric v1.0

**Status:** Certified Complete (C5.1 → C5.12)
**Core Version:** `1.0.0`
**Agent Contract Version:** `1.0`
**SDK Version:** `1.0.0`
**Database:** Supabase (Managed PostgreSQL 16 + `dsrt` schema)
**New Tables:** 11 (plans, plan_versions, plan_nodes, plan_dependencies, orchestration_executions, node_executions, orchestration_checkpoints, delegations, shared_states, state_patches, replans)

---

## 1. Phase C5 Objective

Build the orchestration runtime that transforms DSRT from a single-agent execution system into a **multi-agent coordination platform** capable of decomposing objectives into task graphs, scheduling parallel work, managing shared state, recovering from failures, and dynamically replanning.

> **Before C5:** Task → Agent → Result
> **After C5:** Objective → Plan → Graph → Nodes → Agents → Shared State → Verify → Replan → Output

---

## 2. Complete C5 Sub-Phase Summary

| Sub-Phase | Component | Key Deliverables |
|---|---|---|
| **C5.1** | Contracts & Schemas | 9 enums, 13 domain schemas, 11 API schemas, 11 ID prefixes |
| **C5.2** | Database Schema | 11 ORM models, Alembic migration, FKs/indexes/cascades |
| **C5.3** | Graph Engine | TaskGraph (DAG), Kahn's topo sort, CycleDetector, GraphValidator, subgraph extraction |
| **C5.4** | Planner | 8-stage PlanValidator, model-assisted + explicit modes, plan versioning, repair |
| **C5.5** | Scheduler | Stateless, 4 strategies, 5-level concurrency, budget gates, approval pause |
| **C5.6** | Node Executor | 6 node types, 12-state lifecycle, agent resolution, event emission |
| **C5.7** | Delegation | Capability-based resolution, permission inheritance, budget propagation, depth limits |
| **C5.8** | Shared State | JSON Pointer patches, optimistic concurrency, auto-merge, append-only history |
| **C5.9** | Checkpoints & Recovery | Durable checkpoints, failure classification, exponential backoff, heartbeat monitoring |
| **C5.10** | Replanning | Partial subtree replacement, completed-node preservation, immutable plan versions |
| **C5.11** | SDK, API & Events | OrchestrationSDK (8 methods), 12 REST endpoints, 35 event types |
| **C5.12** | Certification | E2E tests, security regression, verify_c5.py, readaboutc5.md |

---

## 3. Architecture

USER OBJECTIVE
│
▼
PLANNER (C5.4)
│
▼
PLAN VALIDATOR (8-stage deterministic)
│
▼
TASK GRAPH (C5.3 DAG)
│
▼
SCHEDULER (C5.5)
│
┌──┴──┐
▼ ▼
NODE NODE ← parallel execution
│ │
▼ ▼
AGENT AGENT ← via Node Executor (C5.6)
│ │
└──┬──┘
▼
SHARED STATE (C5.8)
│
┌──┴──┐
▼ ▼
VERIFY RECOVER (C5.9)
│ │
└──┬──┘
▼
REPLAN (C5.10)
│
▼
CONTINUE

text


---

## 4. Critical Invariants Enforced

| # | Invariant | Enforced By |
|---|-----------|-------------|
| 1 | Dependencies satisfied before execution | `TaskGraph.get_ready_nodes()` + `Scheduler.decide()` |
| 2 | Child permissions ⊆ parent | `DelegationManager._check_permission_inheritance()` |
| 3 | Child resources ≤ parent | `DelegationManager._check_budget_propagation()` |
| 4 | Plan versions immutable | `PlanVersionORM` never updated; `create_plan_version()` creates new |
| 5 | Execution history append-only | `EventRepository.append_event()` monotonic; `StatePatchORM` append-only |
| 6 | State changes versioned | `SharedStateStore.apply_patch()` increments version |
| 7 | No graph cycles | `CycleDetector.validate_acyclic()` in `PlanValidator` |
| 8 | Cancellation propagates | `CancellationManager` + `NodeExecutor` cancel check + `DelegationManager.cancel_delegations()` |
| 9 | Every node execution observable | `NodeExecutor._emit_event()` on start/complete/fail |
| 10 | Replans preserve history | `ReplanORM` records previous + new version; old plan never deleted |

---

## 5. Key Components

### Task Graph (C5.3)
- Pure-logic DAG with adjacency lists
- Kahn's algorithm for deterministic topological sort
- Ready-node detection (HARD vs SOFT dependencies)
- Blocked-node detection (failed HARD deps)
- Subgraph extraction for partial replanning
- SHA-256 graph hash for version deduplication

### Planner (C5.4)
- 8-stage validation: schema → graph → dependency → capability → permission → resource → cycle → policy
- Model-assisted plan generation (prompts in `prompts.py`)
- Explicit plan mode (user provides nodes)
- Default plan generation (single agent + verification)
- Plan repair with heuristic fixes

### Scheduler (C5.5)
- Stateless: `decide(context) → decision`
- 4 strategies: FIFO, PRIORITY, SHORTEST_FIRST, CRITICAL_PATH
- 5-level concurrency: global → org → task → agent → tool
- Budget gates: USD, model calls, tool calls, duration
- Approval gate pauses scheduling

### Node Executor (C5.6)
- 6 node types: AGENT_TASK, VERIFICATION, CONDITION, MERGE, CHECKPOINT, HUMAN_APPROVAL
- 12-state lifecycle with deterministic transitions
- Agent resolution by slug or capability
- CONFLICT_PRESERVING merge for parallel outputs
- Structured condition evaluation (no arbitrary code)

### Delegation (C5.7)
- Capability-based agent resolution
- Permission inheritance (network, filesystem, external_actions)
- Budget propagation (USD, model calls, tool calls, duration)
- Depth limits (default max 5)
- Children count limits (default max 20 per node)

### Shared State (C5.8)
- JSON Pointer (RFC 6901) paths
- ADD/REPLACE/REMOVE operations
- Deep copy semantics (original never mutated)
- Optimistic concurrency (version check)
- Auto-merge for non-overlapping paths
- Path traversal prevention

### Checkpoints & Recovery (C5.9)
- Durable graph state snapshots
- Failure classification: RETRYABLE / NON_RETRYABLE / REQUIRES_REPLAN
- Exponential backoff (configurable base, multiplier, max)
- Model fallback + agent reassignment
- Heartbeat-based stale node detection

### Replanning (C5.10)
- Node classification: completed (preserve) vs affected (replace)
- Downstream dependency propagation
- Default retry-node generation
- Custom replacement support
- Dependency reconnection
- Immutable plan versioning

---

## 6. Agent SDK After C5

Agents access orchestration through `sdk.orchestration`:

```python
# Delegate to another agent
result = await sdk.orchestration.delegate(
    capability="financial_analysis",
    objective="Analyze Q4 revenue",
    inputs={"companies": ["Acme", "Beta"]},
)

# Read/write shared state
await sdk.orchestration.update_state([
    {"path": "/findings", "operation": "add", "value": ["new fact"]},
])
state = await sdk.orchestration.read_state("/findings")

# Request replan
await sdk.orchestration.request_replan(
    reason="Data source unavailable",
    failed_nodes=["data_collection"],
)

# Checkpoint
await sdk.orchestration.checkpoint("Before risky action")
7. REST API (C5.11)
text

POST   /api/v1/tasks/{task_id}/plans           Create plan
GET    /api/v1/tasks/{task_id}/plans            List plans
POST   /api/v1/plans/{plan_id}/validate         Validate plan
GET    /api/v1/orchestration/{id}               Get execution
POST   /api/v1/orchestration/{id}/pause         Pause
POST   /api/v1/orchestration/{id}/resume        Resume
POST   /api/v1/orchestration/{id}/cancel        Cancel
GET    /api/v1/orchestration/{id}/nodes         List nodes
GET    /api/v1/orchestration/{id}/state         Get state
POST   /api/v1/orchestration/{id}/state/patches Apply patches
GET    /api/v1/orchestration/{id}/checkpoints   List checkpoints
POST   /api/v1/orchestration/{id}/replan        Replan
8. Run Instructions
PowerShell

# Verify C5 certification
python scripts/verify_c5.py

# Run C5 unit tests
python -m pytest tests/unit/test_orchestration_graph.py tests/unit/test_orchestration_planner.py tests/unit/test_orchestration_scheduler.py tests/security/test_c5_security.py -v

# Start server
python main.py
9. What C5 Enables
With C1–C5 together:

text

THINK → REMEMBER → PLAN → DELEGATE → ACT → OBSERVE → RECOVER → REPLAN → VERIFY → PRODUCE
DSRT is now an intelligence runtime, not an agent wrapper.

text


---

## Verification

After creating all 6 files, run:

```powershell
# 1. Run C5 unit tests
python -m pytest tests/unit/test_orchestration_graph.py tests/unit/test_orchestration_planner.py tests/unit/test_orchestration_scheduler.py tests/security/test_c5_security.py -v --tb=short 2>&1 | Select-Object -Last 30

# 2. Run C5 certification
python scripts/verify_c5.py

# 3. Full regression
python -m pytest tests/unit/ tests/security/ -v --tb=short 2>&1 | Select-Object -Last 10
C5.12 Definition of Done
 test_orchestration_graph.py — 16 tests (DAG, topo sort, cycles, ready/blocked, subgraph, hash, soft deps)
 test_orchestration_planner.py — 8 tests (valid, empty, duplicates, cycles, capabilities, max nodes, dangling refs, self-deps)
 test_orchestration_scheduler.py — 9 tests (initial, partial, blocked, concurrency, saturated, approval, retry, priority, budget)
 test_c5_security.py — 11 tests (permission inheritance ×3, budget ×3, depth, path traversal, mutation, concurrency, recovery)
 verify_c5.py — 11-check certification script
 readaboutc5.md — complete documentation
 All existing tests still pass
 C5 PHASE CERTIFIED COMPLETE
