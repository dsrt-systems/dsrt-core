# Part 1: `readaboutc4.md`

Here is the complete C4 documentation. Save this as `docs/readaboutc4.md`:

```markdown
# DSRT Core — Phase C4 Context & Memory Fabric v1.0

**Status:** Certified Complete (C4.1 → C4.12)
**Core Version:** `1.0.0`
**Agent Contract Version:** `1.0`
**SDK Version:** `1.0.0`
**Database:** Supabase (Managed PostgreSQL 16 + `pgvector` + `dsrt` schema)
**New Tables:** 10 (memories, memory_versions, memory_embeddings, memory_sources, memory_links, memory_conflicts, memory_access_logs, memory_retention_policies, memory_consolidation_runs, context_builds)
**Total Tables in `dsrt` schema:** 45+

---

## 1. Phase C4 Objective

Build the persistent intelligence state system that allows DSRT agents to **remember, retrieve, and build upon knowledge across executions** — transforming DSRT from a stateless execution system into a platform for continuous, long-horizon intelligence work.

> **Memory ≠ Chat History. Memory ≠ Context. Memory ≠ Vector Search.**
> Memory is a governed, versioned, provenance-tracked, permission-controlled knowledge fabric.

---

## 2. Complete C4 Sub-Phase Summary

| Sub-Phase | Component | Key Deliverables |
|---|---|---|
| **C4.1** | Memory Contracts & Schemas | `Memory`, `MemoryCreate`, `MemoryVersion`, `MemorySource`, `MemoryLink`, `MemoryConflict`, `MemoryQuery`, `MemoryRetrievalResult`, `MemoryUpdate`, `ContextProfile`, `ContextBuildRequest`, `ContextBuildResult`; 6 new enums (`MemoryType`, `MemoryStatus`, `MemoryScope`, `MemoryImportance`, `MemoryLinkType`, `MemoryVerificationState`) |
| **C4.2** | Database Schema & ORM | 10 new ORM models, Alembic migration `f3ed4d17c604`, 10 new tables with indexes, FKs, cascades in `dsrt` schema |
| **C4.3** | Memory Store & Repository | `MemoryRepository` (CRUD, versioning, search, access logging), `MemoryStore` (write pipeline: validate → dedup → conflict → persist → version → embed → source → audit) |
| **C4.4** | Permissions & Scope | `MemoryPermissionEngine` (5-stage authorization: org boundary → scope access → scope_id matching → org-write approval → ALLOWED), `MemoryAccessPolicy`, `MemoryScopePolicy` |
| **C4.5** | Embeddings & pgvector | `EmbeddingGenerator` (model-independent, local-hash fallback, provider delegation via C2 AdapterRegistry), `EmbeddingStore` (JSON-stored vectors, cosine similarity, scope-filtered search) |
| **C4.6** | Hybrid Retrieval | `HybridRetrievalEngine` (concurrent vector + keyword + temporal queries), `HybridRanker` (6-factor weighted scoring: semantic, lexical, temporal, importance, scope, verification) |
| **C4.7** | Conflict Detection | `ConflictDetector` (duplicate detection at 0.92 threshold, numeric contradiction via regex, negation stance detection), `ConflictDetectionResult` |
| **C4.8** | Context Engine v2 | `ContextEngine` (memory retrieval → C2 ContextCompiler delegation → audit record), `ContextProfileManager` (per-agent profiles), `ContextCompressor` (history summarization, working state truncation) |
| **C4.9** | Consolidation & Retention | `MemoryConsolidator` (episodic → semantic synthesis), `RetentionEnforcer` (TTL expiration) |
| **C4.10** | Memory SDK Integration | `MemorySDKImpl` (replaces C1 stub; write/retrieve/get/update/link via SDK), wired into `build_agent_sdk` factory |
| **C4.11** | Events, Observability & Bug Fixes | `MemoryEventEmitter` (16 C4 event types), C4 error codes, `EmbeddingStore.provider` property, vector candidate field propagation, `ContextEngine` datetime fix + compression wiring, `StateSDKImpl` completeness (`delete`/`set_many`/`clear`), Memory REST API router |
| **C4.12** | Certification | `verify_c4.py` (17-check programmatic sign-off), `readaboutc4.md` |

---

## 3. Architecture

### The Three Fundamental Capabilities After C4

```text
MODEL  → THINK      (C2)
TOOL   → ACT        (C3)
MEMORY → REMEMBER   (C4)
```

### Layered State System

```text
┌───────────────────────────────────────────┐
│              CURRENT CONTEXT              │
│  What the model needs now (C2 Compiler)   │
└──────────────────────┬────────────────────┘
                       │
┌──────────────────────▼────────────────────┐
│             WORKING MEMORY                │
│  Current reasoning / intermediate state   │
└──────────────────────┬────────────────────┘
                       │
┌──────────────────────▼────────────────────┐
│             TASK MEMORY                   │
│  Facts / decisions / evidence             │
└──────────────────────┬────────────────────┘
                       │
┌──────────────────────▼────────────────────┐
│            PROJECT MEMORY                 │
│  Persistent project knowledge             │
└──────────────────────┬────────────────────┘
                       │
┌──────────────────────▼────────────────────┐
│           ORGANIZATION MEMORY             │
│  Approved institutional knowledge         │
└───────────────────────────────────────────┘
```

### Memory Write Pipeline

```text
Agent → sdk.memory.write()
  ↓
MemorySDKImpl (C4.10)
  ↓
MemoryStore.write() (C4.3)
  ├── 1. Validate proposal
  ├── 2. Deduplication check (ConflictDetector + EmbeddingStore)
  ├── 3. Persist memory record
  ├── 4. Create version snapshot
  ├── 5. Generate embedding + detect conflicts
  ├── 6. Attach source provenance
  ├── 7. Log access audit
  └── 8. Emit MEMORY_CREATED event (C4.11)
```

### Hybrid Retrieval Pipeline

```text
Query
  ↓
HybridRetrievalEngine.search() (C4.6)
  ├── Vector search (EmbeddingStore, pgvector cosine similarity)
  ├── Keyword search (PostgreSQL ILIKE)
  └── Temporal search (valid_from/valid_until range)
  ↓
HybridRanker.rank_and_merge()
  ├── Semantic similarity (0.40 weight)
  ├── Keyword match (0.20)
  ├── Temporal recency (0.10, 30-day half-life)
  ├── Importance (0.10)
  ├── Scope relevance (0.10)
  └── Verification status (0.10)
  ↓
MemoryRetrievalResponse
```

### Context Engine v2

```text
ContextBuildRequest
  ↓
ContextEngine.build_context() (C4.8)
  ├── 1. Resolve agent profile (ContextProfileManager)
  ├── 2. Retrieve memories per scope (HybridRetrievalEngine)
  ├── 3. Configure token budget (ContextBudget)
  ├── 4. Delegate to C2 ContextCompiler
  ├── 5. Apply compression if needed (ContextCompressor)
  └── 6. Persist audit record (ContextBuildORM)
  ↓
(CompiledContext, ContextBuildResult)
```

---

## 4. Key Invariants Enforced

| # | Invariant | Enforcement |
|---|-----------|-------------|
| 1 | Memory is not automatically truth | `MemoryVerificationState` (UNVERIFIED/VERIFIED/CONTRADICTED/DISPUTED); agents propose, Core persists |
| 2 | Organization boundary is absolute | `MemoryPermissionEngine` stage 1; `MemoryStore.get()` checks `organization_id` |
| 3 | Memory is versioned, never silently mutated | `MemoryVersionORM` immutable snapshots; `MemoryStore.update()` creates new version |
| 4 | Conflicts are preserved, not overwritten | `ConflictDetector` creates `MemoryConflictORM` + `CONTRADICTS` link; both memories remain |
| 5 | Duplicates are detected and deduplicated | `ConflictDetector.analyze_proposal()` at 0.92 similarity threshold; returns existing memory |
| 6 | Every memory has provenance | `MemorySourceORM` tracks source_type, execution_id, agent_slug, tool_execution_id, url |
| 7 | Scope governs visibility | `MemoryScope` enum (EXECUTION/TASK/PROJECT/USER/AGENT/ORGANIZATION/WORLD); cross-project denied by default |
| 8 | Embeddings are model-independent | `EmbeddingGenerator` delegates to C2 Provider Adapter; local-hash fallback for testing |
| 9 | Context compilation is auditable | `ContextBuildORM` records memory_ids, artifact_ids, token counts, compression, retrieval strategy |
| 10 | Memory events flow to trajectory | `MemoryEventEmitter` emits 16 event types through `ExecutionKernel.emit_event()` |

---

## 5. Memory Types

| Type | Purpose | Example |
|------|---------|---------|
| `WORKING` | Short-lived execution state | current_plan, pending_actions |
| `EPISODIC` | What happened | "On Sep 20, agent searched A, B, C" |
| `SEMANTIC` | What is believed true | "Company X was founded in 2018" |
| `PROCEDURAL` | How something is done | "For research: search → cross-check → synthesize" |
| `ENTITY` | Persistent entity info | "Acme Corp: industry, products, executives" |
| `DOCUMENT` | Large document representations | Chunked PDF with embeddings |

---

## 6. Database Schema (C4 additions)

### memories
```
id (PK, mem_*)  organization_id (FK)  scope_type  scope_id  memory_type
content  structured_data (JSONB)  status  importance  confidence
verification_state  source_type  source_id  observed_at  valid_from
valid_until  superseded_by (FK→memories)  created_by  version  metadata_json
```

### memory_versions
```
id (PK, mev_*)  memory_id (FK)  version  content  structured_data
previous_version  change_reason  source_type  source_id  author
```

### memory_embeddings
```
id (PK, mmb_*)  memory_id (FK)  embedding (Text/JSON)  embedding_model
embedding_dimensions
```

### memory_sources
```
id (PK, msr_*)  memory_id (FK)  source_type  source_id  tool_execution_id
execution_id  agent_slug  url  metadata_json
```

### memory_links
```
id (PK, mln_*)  source_memory_id (FK)  target_memory_id (FK)
link_type  confidence  metadata_json
```

### memory_conflicts
```
id (PK, mcf_*)  memory_a_id (FK)  memory_b_id (FK)  conflict_type
description  resolution  resolved  metadata_json
```

### memory_access_logs
```
id (PK, mac_*)  memory_id (FK)  organization_id  user_id  agent_slug
execution_id  action  scope_type  scope_id  result  reason  metadata_json
```

### memory_retention_policies
```
id (PK, mrt_*)  organization_id (FK)  scope_type  memory_type  importance
ttl_days  refresh_interval_days  auto_archive  auto_delete  legal_hold
```

### memory_consolidation_runs
```
id (PK, mem_*)  organization_id  scope_type  scope_id  episodes_processed
memories_created  conflicts_detected  memories_superseded  status
```

### context_builds
```
id (PK, cbd_*)  execution_id (FK)  task_id (FK)  context_hash  total_tokens
memory_items_included  evidence_items_included  artifact_items_included
event_items_included  memory_ids (JSONB)  artifact_ids (JSONB)
event_ids (JSONB)  retrieval_strategy  compression_applied  state_dropped
build_time_ms  metadata_json
```

---

## 7. Agent SDK After C4

Agents use the frozen `MemorySDK` Protocol (unchanged from C1):

```python
# Write a memory
memory_id = await sdk.memory.write(SDKMemoryRecord(
    memory_type="semantic",
    content="PostgreSQL is the primary database.",
    scope="project",
    importance="important",
))

# Retrieve memories
results = await sdk.memory.retrieve(
    query="database architecture decisions",
    scope="project",
    limit=10,
)

# Get specific memory
mem = await sdk.memory.get(memory_id)

# Update memory (creates new version)
updated = await sdk.memory.update(memory_id, {
    "content": "PostgreSQL 16 with pgvector is the primary database.",
    "change_reason": "Version upgrade",
})

# Link memories
await sdk.memory.link(source_id, target_id, "SUPPORTS")
```

Agents **never** know whether memory is backed by PostgreSQL, pgvector, Redis, or any future storage system.

---

## 8. Context Profiles

Per-agent context allocation (C4 §47):

| Agent | Semantic | Episodic | Artifacts | Max Memory Items |
|-------|----------|----------|-----------|-----------------|
| `research_intelligence` | 0.8 | 0.2 | 0.7 | 30 |
| `software_engineering` | 0.4 | 0.3 | 0.8 | 20 |
| default | 0.5 | 0.3 | 0.5 | 15 |

---

## 9. C4 Event Types

```
MEMORY_PROPOSED          MEMORY_CREATED           MEMORY_RETRIEVED
MEMORY_UPDATED           MEMORY_SUPERSEDED        MEMORY_CONFLICT_DETECTED
MEMORY_EXPIRED           MEMORY_ARCHIVED          MEMORY_DELETED
MEMORY_LINKED            MEMORY_DEDUPLICATED      MEMORY_VALIDATED
CONTEXT_BUILD_STARTED    CONTEXT_BUILD_COMPLETED
CONTEXT_RETRIEVAL_STARTED  CONTEXT_RETRIEVAL_COMPLETED
CONTEXT_COMPRESSION_STARTED  CONTEXT_COMPRESSION_COMPLETED
```

---

## 10. C4 Error Codes

```
MEMORY_NOT_FOUND         MEMORY_ACCESS_DENIED     MEMORY_WRITE_DENIED
MEMORY_CONFLICT          MEMORY_SCHEMA_INVALID    MEMORY_STORAGE_FAILURE
MEMORY_EMBEDDING_FAILURE RETRIEVAL_FAILURE        CONTEXT_TOO_LARGE
CONTEXT_COMPRESSION_FAILURE  CONTEXT_PERMISSION_FAILURE  PROVENANCE_FAILURE
```

---

## 11. REST API (C4.11)

```
POST   /api/v1/memories              Create memory
GET    /api/v1/memories/{id}         Get memory
PATCH  /api/v1/memories/{id}         Update memory
DELETE /api/v1/memories/{id}         Archive memory
POST   /api/v1/memories/retrieve     Hybrid search
```

---

## 12. Repository Structure

```
dsrt-core/
├── core/
│   ├── context/
│   │   ├── engine.py          (C4.8) ContextEngine v2
│   │   ├── profiles.py        (C4.8) ContextProfileManager
│   │   └── compression.py     (C4.8) ContextCompressor
│   ├── memory/
│   │   ├── store/store.py     (C4.3) MemoryStore
│   │   ├── permissions/       (C4.4) MemoryPermissionEngine
│   │   ├── embeddings/        (C4.5) EmbeddingGenerator + EmbeddingStore
│   │   ├── retrieval/         (C4.6) HybridRetrievalEngine + HybridRanker
│   │   ├── conflicts/         (C4.7) ConflictDetector
│   │   ├── consolidation/     (C4.9) MemoryConsolidator
│   │   ├── retention/         (C4.9) RetentionEnforcer
│   │   └── observability.py   (C4.11) MemoryEventEmitter
│   └── storage/models/
│       ├── memory.py          (C4.2) 6 ORM models
│       ├── memory_access.py   (C4.2) 3 ORM models
│       └── context.py         (C4.2) ContextBuildORM
├── schemas/domain/
│   ├── memory.py              (C4.1) Memory domain schemas
│   ├── context.py             (C4.1) Context schemas
│   └── enums.py               (C4.1+C4.11) Memory enums + events + errors
├── sdk/agent/
│   ├── interfaces/memory.py   (C1 frozen) MemorySDK Protocol
│   └── adapters/memory_adapter.py (C4.10) MemorySDKImpl
├── migrations/versions/
│   └── f3ed4d17c604_c4_memory_context_schema.py
├── scripts/verify_c4.py       (C4.12)
└── docs/readaboutc4.md        (this file)
```

---

## 13. Run Instructions

```powershell
# Verify C4 certification
python scripts/verify_c4.py

# Run all C4 tests
python -m pytest tests/unit/test_memory_store.py tests/unit/test_memory_permissions.py tests/unit/test_memory_sdk_impl.py tests/unit/test_memory_workers.py tests/unit/test_embeddings.py tests/unit/test_hybrid_retrieval.py tests/unit/test_conflict_detection.py tests/unit/test_context_engine_v2.py tests/unit/test_context_compression.py -v

# Start server (memory API available at /api/v1/memories)
python main.py
```

---

## 14. Known Limitations (v1.0)

1. **Embeddings stored as JSON text**, not native pgvector `VECTOR(1536)` column. Cosine similarity computed in Python. Native pgvector operators planned for C4 v1.1.
2. **Vector candidates missing some fields** (confidence, observed_at) during ranking. Full hydration planned for C4 v1.1.
3. **Consolidation uses naive concatenation**. Model-assisted synthesis planned for C5+ when orchestration provides multi-step workflows.
4. **ContextCompressor uses truncation, not model-based summarization**. True LLM summarization planned for C5+.
5. **No Redis caching** for compiled contexts yet. Planned for C4 v1.1.

---

## 15. What C4 Unlocks

After C4, DSRT supports:

```text
Day 1: Research → Evidence → Report → Memories stored
Day 7: "Continue the research" → Memories retrieved → Work continues
Day 14: Model switch (GPT → Gemini) → Canonical state preserved → No data loss
Day 30: Consolidation worker → Episodic memories → Stable semantic knowledge
```

This is the foundation for **persistent AI work**.
```

---

# Part 2: C5 Orchestration Fabric — Complete Analysis & Build Plan

## Architecture Analysis

C5 is the **most structurally complex phase** because it introduces an entirely new execution paradigm. Before C5, DSRT executes `Task → Agent → Result`. After C5, it executes `Objective → Plan → Graph → Nodes → Agents → Shared State → Verification → Replan → Output`.

### What C5 Builds On (existing infrastructure)

| C5 Needs | Provided By | File |
|----------|------------|------|
| Agent resolution by capability | C1 AgentRegistry | `core/agents/registry.py` |
| Capability matching | C1 CapabilityRegistry | `core/capabilities/registry.py` |
| Execution lifecycle | C1 ExecutionKernel | `core/kernel/kernel.py` |
| Event emission | C1 EventBus + EventRepo | `core/events/bus.py`, `core/repositories/event_repository.py` |
| Resource limits | C1 ResourceController | `core/kernel/resources.py` |
| Cancellation | C1 CancellationManager | `core/kernel/cancellation.py` |
| Model execution | C2 ModelGateway | `core/models/gateway/gateway.py` |
| Context compilation | C4 ContextEngine | `core/context/engine.py` |
| Memory retrieval | C4 HybridRetrievalEngine | `core/memory/retrieval/engine.py` |
| Tool execution | C3 ToolExecutionEngine | `core/tools/execution/engine.py` |
| Agent execution | C1 AgentAdapter | `core/agents/adapter/adapter.py` |
| SDK factory | C3 build_agent_sdk | `sdk/agent/runtime/factory.py` |
| Approval system | C3 ApprovalService | `core/tools/approvals/service.py` |
| World resolution | C3 WorldManager | `core/worlds/manager/manager.py` |

### What C5 Introduces (new subsystems)

1. **Planner** — converts objectives into DAGs (model-assisted, deterministically validated)
2. **Task Graph Engine** — DAG data structure, cycle detection, topological ordering
3. **Scheduler** — determines which nodes are ready, manages concurrency
4. **Node Executor** — runs individual nodes through agent/model/tool pipelines
5. **Delegation Runtime** — capability-based agent-to-agent delegation
6. **Shared State Engine** — versioned state patches with optimistic concurrency
7. **Checkpoint System** — durable execution snapshots for crash recovery
8. **Replanning Engine** — partial graph replacement on failure
9. **Orchestration SDK** — `sdk.orchestration.*` for agents
10. **Orchestration API** — REST routes for plan/execute/pause/resume/replan

---

## C5 Sub-Phase Design (12 sub-phases)

### C5.1 — Orchestration Contracts & Domain Schemas
**What:** All Pydantic schemas, enums, and data contracts for the orchestration system.
**Builds:**
- `schemas/domain/enums.py` — extend with: `PlanStatus`, `NodeStatus`, `NodeType`, `DependencyType`, `OrchestrationStatus`, `DelegationStatus`, `RecoveryAction`, `MergePolicy`, plus ~30 C5 event types
- `schemas/domain/orchestration.py` — `Plan`, `PlanVersion`, `PlanNode`, `PlanDependency`, `OrchestrationExecution`, `NodeExecution`, `OrchestrationCheckpoint`, `Delegation`, `StatePatch`, `Replan`, `OrchestrationPolicy`, `PlanRequest`, `PlanConstraints`
- `schemas/api/orchestration.py` — API request/response schemas
- `core/storage/identifiers.py` — extend with `pln_`, `pnv_`, `pnd_`, `pdp_`, `oex_`, `nex_`, `ock_`, `dlg_`, `spc_`, `rpl_` prefixes

### C5.2 — Database Schema & ORM Models
**What:** All C5 tables as SQLAlchemy ORM models + Alembic migration.
**Builds:**
- `core/storage/models/orchestration.py` — `PlanORM`, `PlanVersionORM`, `PlanNodeORM`, `PlanDependencyORM`
- `core/storage/models/orchestration_execution.py` — `OrchestrationExecutionORM`, `NodeExecutionORM`
- `core/storage/models/orchestration_checkpoint.py` — `OrchestrationCheckpointORM`
- `core/storage/models/delegation.py` — `DelegationORM`, `StatePatchORM`, `ReplanORM`
- Update `core/storage/models/__init__.py`
- Alembic migration `c5_orchestration_schema`

### C5.3 — Task Graph Engine
**What:** Pure-logic DAG implementation with cycle detection and topological ordering.
**Builds:**
- `core/orchestration/graph/__init__.py`
- `core/orchestration/graph/graph.py` — `TaskGraph` (adjacency list, add_node, add_edge, get_ready_nodes, get_downstream)
- `core/orchestration/graph/cycle_detection.py` — `validate_acyclic()` (DFS-based)
- `core/orchestration/graph/validator.py` — `GraphValidator` (schema + dependency + capability + cycle checks)

### C5.4 — Planner
**What:** Converts objectives into validated Plans.
**Builds:**
- `core/orchestration/planner/__init__.py`
- `core/orchestration/planner/planner.py` — `Planner` (model-assisted plan generation via C2 ModelGateway)
- `core/orchestration/planner/validator.py` — `PlanValidator` (deterministic: schema, graph, capability, permission, resource, cycle, policy)

### C5.5 — Scheduler
**What:** Determines which nodes should execute now.
**Builds:**
- `core/orchestration/scheduler/__init__.py`
- `core/orchestration/scheduler/scheduler.py` — `Scheduler` (ready-node detection, dependency resolution, concurrency limits, resource checks)

### C5.6 — Node Executor
**What:** Executes individual nodes through the agent/model/tool pipeline.
**Builds:**
- `core/orchestration/executor/__init__.py`
- `core/orchestration/executor/node_executor.py` — `NodeExecutor` (agent resolution, SDK build, context compilation, execution, output validation)
- `core/orchestration/executor/lifecycle.py` — `NodeLifecycleManager` (state machine transitions)

### C5.7 — Delegation Runtime
**What:** Capability-based agent-to-agent delegation with budget propagation.
**Builds:**
- `core/orchestration/delegation/__init__.py`
- `core/orchestration/delegation/delegation.py` — `DelegationManager` (capability resolution, agent selection, parent-child execution, permission inheritance, budget propagation, depth limits)

### C5.8 — Shared State Engine
**What:** Versioned shared state with optimistic concurrency.
**Builds:**
- `core/orchestration/state/__init__.py`
- `core/orchestration/state/state_store.py` — `SharedStateStore` (get, apply_patch, get_version)
- `core/orchestration/state/patches.py` — `StatePatchValidator` (JSON Pointer path validation, operation validation)
- `core/orchestration/state/concurrency.py` — `OptimisticConcurrencyControl` (version check, conflict detection)

### C5.9 — Checkpoint & Recovery
**What:** Durable checkpoints and crash recovery.
**Builds:**
- `core/orchestration/checkpoints/__init__.py`
- `core/orchestration/checkpoints/checkpoint.py` — `CheckpointManager` (create, restore, list)
- `core/orchestration/recovery/__init__.py`
- `core/orchestration/recovery/recovery.py` — `RecoveryManager` (retry, fallback, reassignment, heartbeat monitoring)

### C5.10 — Replanning Engine
**What:** Partial graph replacement on failure.
**Builds:**
- `core/orchestration/replanning/__init__.py`
- `core/orchestration/replanning/replanner.py` — `Replanner` (trigger detection, subtree replacement, plan versioning, completed-node preservation)

### C5.11 — Orchestration SDK, API & Events
**What:** Agent-facing SDK + REST API + event emission.
**Builds:**
- `sdk/agent/interfaces/orchestration.py` — `OrchestrationSDK` Protocol
- `sdk/agent/adapters/orchestration_adapter.py` — `OrchestrationSDKImpl`
- `sdk/agent/sdk.py` — add `orchestration: OrchestrationSDK` field
- `sdk/agent/runtime/factory.py` — wire OrchestrationSDKImpl
- `core/api/routers/orchestration.py` — REST routes
- `core/api/app.py` — mount router
- Event emission wired into all orchestration components

### C5.12 — Golden Path, Security & Certification
**What:** E2E tests, security regression, certification.
**Builds:**
- `tests/integration/test_c5_golden_path.py` — multi-agent research workflow
- `tests/unit/test_task_graph.py`, `test_scheduler.py`, `test_state_patches.py`, `test_cycle_detection.py`
- `tests/security/test_delegation_security.py`
- `scripts/verify_c5.py`
- `docs/readaboutc5.md`

---

## C5 Dependency Graph

```
C5.1 (Contracts/Schemas)
  ↓
C5.2 (Database/ORM)
  ↓
C5.3 (Graph Engine) ← pure logic, no DB
  ↓
C5.4 (Planner) ← needs C5.3 + C1 registries
  ↓
C5.5 (Scheduler) ← needs C5.3
  ↓
C5.6 (Node Executor) ← needs C5.5 + C1-C4 infrastructure
  ↓
C5.7 (Delegation) ← needs C5.6 + C1 AgentRegistry
  ↓
C5.8 (Shared State) ← needs C5.2
  ↓
C5.9 (Checkpoints/Recovery) ← needs C5.6 + C5.8
  ↓
C5.10 (Replanning) ← needs C5.4 + C5.3
  ↓
C5.11 (SDK/API/Events) ← needs all above
  ↓
C5.12 (Certification) ← needs all above
```

---

