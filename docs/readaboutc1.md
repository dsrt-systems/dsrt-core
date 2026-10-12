# DSRT Core — Phase C1 Foundation & Agent Contract v1.0

**Status:** Certified Complete (C1.1 → C1.14)  
**Core Version:** `1.0.0`  
**Agent Contract Version:** `1.0`  
**SDK Version:** `1.0.0`  
**Database:** Supabase (Managed PostgreSQL 16 + `pgvector` + `dsrt` schema)  
**Reference Agent:** `research_intelligence@1.0.0`  

---

## 1. Phase C1 Objective

Build the stable execution substrate and Agent Contract through which every future DSRT Agent, user workflow, enterprise workload, and future Arena benchmark will run.

DSRT Core is **an operating system + execution runtime + intelligence control plane**. Agents are specialized professional processes that run on top of it.

---

## 2. Complete C1 Sub-Phase Summary

| Sub-Phase | Component | Responsibilities |
|---|---|---|
| **C1.1** | Project Setup & Env | FastAPI app factory, Pydantic settings, structlog structured logging, `main.py` |
| **C1.2** | Database Foundation | Supabase PostgreSQL async connection pool + Alembic migrations, 16 ORM models |
| **C1.3** | Core Object Model | Pydantic v2 domain schemas, ULID identifiers (`org_`, `usr_`, `tsk_`, `exe_`, `evt_`, `art_`), `configuration_hash` |
| **C1.4** | Security Boundary | bcrypt password hashing, JWT token service, SecurityContext, PermissionEngine, `X-DSRT-Organization` header, `/auth` API |
| **C1.5** | Agent & Capability Registries | `CapabilityRegistry`, `AgentRegistry`, `AgentValidator` (contract version, core compatibility, capability matching), `/capabilities` & `/agents` APIs |
| **C1.6** | Execution Kernel & Lifecycle | `ExecutionKernel` (CNS of DSRT), state machines (`TaskStatus`, `ExecutionStatus`), `/tasks` & `/executions` APIs |
| **C1.7** | Event System | Monotonic event sequencing per execution (`sequence = 1, 2, 3...`), in-memory async `EventBus` pub/sub, `/executions/{id}/events` trajectory API |
| **C1.8** | Agent SDK & Contract Protocols | `DSRTAgentSDK` (10 Protocols), `DSRTAgent` contract Protocol, `AgentAdapter` mediator, Core SDK `Impl` classes |
| **C1.9** | Core API Integration | Artifacts REST API, finalized FastAPI router mounts |
| **C1.10** | Resource & Cancellation | `ResourceController` (budget enforcement), `CancellationManager` (`asyncio.Event` distributed abort) |
| **C1.11** | Observability | `BENCHMARK_RECORD` event injection, `X-Request-ID` middleware, `/api/v1/executions/{id}/telemetry` endpoint for C8 Arena |
| **C1.12** | Reference Agent | `agents/research_intelligence/` buildable package implementing the `DSRTAgent` protocol purely via the SDK |
| **C1.13** | Contract Tests & E2E | `ContractComplianceSuite` harness, C1 §53 Golden Path Test |
| **C1.14** | Certification | `scripts/verify_c1.py` programmatic sign-off |

---

## 3. Key Invariants Enforced (Architectural Boundaries)

1. **Agents never import provider SDKs, tool SDKs, or other agents directly.** All interaction flows through the injected `DSRTAgentSDK`.
2. **Core never contains domain logic.** The `ExecutionKernel` coordinates lifecycles; it does not contain `if agent == "research"` statements.
3. **Every execution records a full version fingerprint.** (`executions.configuration_hash`) — this is mandatory for C8 Arena reproducibility.
4. **Credentials never appear in agent state or logs.** Structlog contextvars and payload standards enforce this.
5. **Contracts freeze; internals evolve.** Agents rely on the Pydantic domain schemas and `Protocol` interfaces. Core implementations (`ContextSDKImpl`, etc.) can be replaced in later phases without breaking the Agent package.
6. **Deterministic infrastructure.** ULID IDs, monotonic sequence event trajectories, and strict state machine transitions (`validate_execution_transition`).
7. **Verification is an independent authority.** Agents can request verification, but they cannot mark their own work as verified.
8. **Cancellation propagates.** A user abort signal correctly shuts down the Kernel, AgentAdapter, and underlying task queues.

---

## 4. Run Instructions

### Start API Server
```powershell
python main.py


---

## What C1 Delivers

C1 establishes the foundational execution system and the stable Agent Contract through which every future DSRT Agent will connect. Nothing here is domain-specific — this is the operating fabric.

## Architecture Principle

DSRT Core is a **model-independent intelligence execution system**, not "a wrapper around LLM APIs." Specialized agents, models, tools, memory, environments, verification systems, and evaluation systems connect through **stable contracts**.

---

## Sub-Phases Completed

### C1.1 — Project Setup + Environment
- Python 3.13 project with venv
- FastAPI + async SQLAlchemy + Pydantic v2 + structlog + pytest-asyncio
- Structured logging (`core/observability/logging.py`)
- Configuration via `.env` (`core/config.py`)
- FastAPI application factory (`core/api/app.py`)
- Version identity (`core/version.py`)
- Health endpoint with component status

### C1.2 — Database Foundation (Supabase)
- **Supabase-managed PostgreSQL 15** with pgvector, pgcrypto, uuid-ossp extensions
- **Dedicated `dsrt` schema** — isolated from Supabase's built-in `public`/`auth`/`storage` schemas
- Async connection pooling via **Session Pooler** (`asyncpg` driver)
- Separate **Direct Connection** URL for Alembic migrations (pooler doesn't support all migration operations)
- Prepared-statement caching disabled (required for pgbouncer/pooler compatibility)
- Automatic `search_path` configuration on every connection
- ULID-based identifiers with type prefixes (`core/storage/identifiers.py`)
- **16 SQLAlchemy 2.0 async ORM models** implementing the complete C1 schema:
  - `organizations`, `users`, `organization_members`
  - `capabilities`
  - `agents`, `agent_versions`, `agent_capabilities`
  - `providers`, `models`
  - `tasks`, `executions`, `execution_events`
  - `artifacts`
  - `verification_runs`, `verification_results`
  - `usage_records`
- Alembic async migrations, initial schema deployed
- Database health check integrated into `/health` endpoint

### C1.3 — Core Object Model + Domain Schemas
- **Pydantic v2 domain schemas** in `schemas/domain/`, separating persistence (ORM) from contracts (Pydantic)
- **Fixed vocabulary enums** — `AgentStatus`, `ExecutionStatus`, `EventType`, `ErrorCode`, `RiskLevel`, `ArtifactType`, `VerificationStatus`, etc.
- **AgentManifest** contract with `AgentIdentity`, `AgentRequirements`, `AgentPermissions` sub-contracts
- **Configuration fingerprint** (`core/kernel/fingerprint.py`) — deterministic SHA-256 hash of execution config
- Comprehensive schema unit tests

---

## Supabase Setup Notes

1. Project created at supabase.com
2. Extensions enabled: `pgcrypto`, `uuid-ossp`, `vector`
3. Dedicated schema `dsrt` created
4. Two connection URLs configured:
   - `DSRT_DATABASE_URL` — Session Pooler (for app)
   - `DSRT_DATABASE_MIGRATION_URL` — Direct Connection (for Alembic)
5. All tables scoped to `dsrt` schema

---

## Key Invariants Enforced

| # | Invariant | Enforcement |
|---|-----------|-------------|
| 1 | Every execution records full version fingerprint | `executions.core_version`, `agent_version_id`, `model_id`, `contract_version`, `configuration_hash` |
| 2 | Contracts frozen, internals evolve | Pydantic schemas + `contract_version` field |
| 3 | Deterministic infrastructure | ULID IDs, monotonic event sequences, immutable events |
| 4 | Estimated cost ≠ provider-reported cost | Separate `UsageRecord.estimated_cost_usd` vs `provider_reported_cost_usd` |
| 5 | Tenant isolation | Every business table has `organization_id` FK |
| 6 | Everything versioned | `AgentVersion`, `Model.version`, `Capability.version`, `contract_version` |

---

## Repository Structure

dsrt-core/
├── core/
│ ├── api/ (C1.1) FastAPI app
│ ├── config.py (C1.1) Settings loader with Supabase URLs
│ ├── kernel/
│ │ └── fingerprint.py (C1.3) Configuration fingerprint
│ ├── observability/
│ │ └── logging.py (C1.1) Structured logging
│ ├── storage/
│ │ ├── database.py (C1.2) DatabaseManager (Supabase-aware)
│ │ ├── identifiers.py (C1.2) ULID IDs
│ │ └── models/ (C1.2) 16 ORM models
│ └── version.py (C1.1) Version constants
├── schemas/
│ └── domain/ (C1.3) Pydantic domain schemas
├── migrations/ (C1.2) Alembic migrations (uses direct connection)
├── tests/
│ ├── conftest.py (C1.2) Shared fixtures
│ ├── unit/ (C1.3) Schema + fingerprint + ID tests
│ ├── integration/ (C1.2) Database tests
│ └── test_health.py (C1.1) Health endpoint tests
├── .env (C1.1) Environment (with Supabase URLs)
├── main.py (C1.1) Entry point
├── requirements.txt (C1.1) Dependencies
└── pyproject.toml (C1.1) Project config

text


---

## Verification

```powershell
# Run all tests
pytest -v

# Start server
python main.py

# Verify
curl http://localhost:8000/health
Upcoming C1 Sub-Phases
C1.4 — Security (Auth + Organization + Permissions)
C1.5 — Agent Contract + Registry + Capability Registry
C1.6 — Execution Kernel + Task/Execution Lifecycle
C1.7 — Event System
C1.8 — SDK Contracts
C1.9 — Core API
C1.10 — Resource Controller + Cancellation + Error Normalization
C1.11 — Observability + Benchmark Hooks
C1.12 — Reference Research Agent v1.0
C1.13 — Contract Tests + Golden Path E2E
C1.14 — Production Validation
text


---

## Final Verification Checklist

Run this exact sequence:

```powershell
# 1. Verify Supabase connection first
python -c "from core.config import get_settings; s = get_settings(); print('URL configured:', 'YOUR_PROJECT_REF' not in s.database_url)"
# Must print: URL configured: True

# 2. Generate migration
alembic revision --autogenerate -m "c1_initial_schema"

# 3. Inspect the generated file in migrations/versions/ — should show all 16 tables with schema='dsrt'

# 4. Apply migration
alembic upgrade head

# 5. Verify in Supabase Dashboard → Table Editor → schema dropdown → dsrt
#    You should see 17 tables (16 + alembic_version)

# 6. Start server
python main.py
# Should show: dsrt_core_ready
# Ctrl+C to stop

# 7. Run ALL tests
pytest -v


---

### C1.4 — Security (Auth + Organization + Permissions)

- **Password hashing** via bcrypt (`core/security/passwords/`) — 12 rounds default, 72-byte input enforced, timing-safe verification
- **JWT token service** (`core/security/tokens/`) — HS256, short-lived access tokens carrying only `sub` (user_id) and `jti`; identity re-derived from DB every request
- **Repository pattern** (`core/repositories/`) — `UserRepository`, `OrganizationRepository` isolate all ORM access; services never touch SQLAlchemy directly
- **Auth service** (`core/security/auth/`) — atomic user + first-organization registration (user becomes OWNER); uniform error for unknown-email vs wrong-password (no enumeration); dummy bcrypt hash preserves timing on missing users
- **SecurityContext** (`core/security/context/`) — the immutable identity object flowing through every authenticated request; carries user, memberships, resolved active organization, token jti
- **PermissionEngine** (`core/security/permissions/`) — evaluates the C1 §36 chain (User → Org → future stages); role hierarchy: VIEWER < MEMBER < ADMIN < OWNER
- **FastAPI dependencies** (`core/api/dependencies/`) — clean layering: `get_session` → `get_*_repository` → `get_auth_service` → `get_security_context` → `require_active_organization`
- **Normalized error taxonomy** (`core/api/errors/`) — every error surfaces via a common envelope: `{"error": {"code": ErrorCode, "message": str, "metadata": dict}}`; provider details never leak; unhandled exceptions become `INTERNAL_ERROR` with logged trace
- **Auth API endpoints**:
  - `POST /api/v1/auth/register` — creates user + initial organization + issues token (201)
  - `POST /api/v1/auth/login` — credentials → token (200)
  - `GET  /api/v1/auth/me` — protected; returns identity + memberships + resolved active org
- **Organization header**: `X-DSRT-Organization` sets the active org context; membership is verified server-side (never trusted from client)

#### Invariants Enforced

- Passwords are never in logs, events, tokens, artifacts, exceptions, or serialized output
- Tokens carry minimum claims; server always re-derives full identity
- `organization_id` from the client is verified against server-side membership before any resource access
- Login errors are uniform — no user enumeration via response differences or timing
- Every error uses the DSRT `ErrorCode` taxonomy — no leaking of framework, database, or provider error text




---

### C1.5 — Agent Contract + Registry + Capability Registry

- **Capability Registry Service** (`core/capabilities/registry.py`) — registers and manages global machine-readable capabilities (`slug`, `input_schema`, `output_schema`, `risk_level`)
- **Agent Validator** (`core/agents/validator.py`) — validates `AgentManifest` against Core contract version `1.0`, core version compatibility, and registered capabilities
- **Agent Registry Service** (`core/agents/registry.py`) — manages agent registration pipeline, resolution of active agent versions by slug/constraint, and capability search
- **API Endpoints**:
  - `GET /api/v1/capabilities` — list all capabilities
  - `POST /api/v1/capabilities` — register system capability
  - `GET /api/v1/agents` — list active agents
  - `GET /api/v1/agents/{slug}` — agent detail and latest active version
  - `POST /api/v1/agents/register` — validate & register an AgentPackage version




  ---

### C1.6 — Execution Kernel + Task/Execution Lifecycle

- **Task & Execution Repositories** (`core/repositories/task_repository.py`, `core/repositories/execution_repository.py`)
- **Lifecycle State Machines** (`core/kernel/lifecycle.py`) — deterministic transition validation for `TaskStatus` and `ExecutionStatus`
- **Execution Kernel** (`core/kernel/kernel.py`) — CNS of DSRT: validates permissions, resolves `AgentVersion`, computes configuration fingerprint (`configuration_hash`), merges default & task resource limits, manages execution creation & cancellation
- **API Endpoints**:
  - `POST /api/v1/tasks` — create task
  - `GET /api/v1/tasks` — list organization tasks
  - `GET /api/v1/tasks/{id}` — get task details
  - `POST /api/v1/tasks/{id}/execute` — queue a new execution attempt
  - `GET /api/v1/executions/{id}` — get execution state
  - `POST /api/v1/executions/{id}/cancel` — cancel execution

  ---

### C1.7 — Event System

- **Monotonic Event Sequencing** (`core/repositories/event_repository.py`) — guarantees sequence numbers increment (`1, 2, 3...`) per execution
- **Event Bus** (`core/events/bus.py`) — async in-memory pub/sub fanout for trajectory events
- **Execution Trajectory Instrumentation** — `ExecutionKernel` automatically emits `EXECUTION_CREATED`, `EXECUTION_STARTED`, `EXECUTION_COMPLETED`, `EXECUTION_FAILED`, `EXECUTION_CANCELLED`
- **Agent Event SDK** (`sdk/agent/events.py`) — abstract contract allowing agent packages to record domain events
- **API Endpoint**: `GET /api/v1/executions/{execution_id}/events` — view execution trajectory events ordered by sequence


---

### C1.8 — Agent SDK & Contract Protocols

The frozen boundary between DSRT Core and every DSRT Agent (C1 §9, §16, §17-26).

**SDK Contracts (Protocols):**
- `ModelSDK` (C1 §18-19) — reasoning capability, provider-neutral
- `ToolSDK` (C1 §20-21) — action capability, permission-controlled
- `ContextSDK` (C1 §22) — structured execution context
- `MemorySDK` (C1 §23) — future memory fabric (agents propose, Core decides)
- `EventSDK` (C1 §24) — trajectory emission (AGENT_EVENT taxonomy)
- `ArtifactSDK` (C1 §25) — durable output creation with content hashing
- `VerificationSDK` (C1 §26) — verification requests
- `StateSDK` (C1 §27) — in-execution working state
- `LoggingSDK` — structured, correlated logging via structlog
- `BenchmarkSDK` (C1 §39-40) — telemetry hooks for future Arena

**Master SDK:**
- `DSRTAgentSDK` — the single frozen dataclass injected into every agent, bundling all Protocol instances plus `sdk_version` and `contract_version` stamps

**Agent Contract (`DSRTAgent`) (C1 §9):**
- `identity: AgentIdentity` (immutable)
- `manifest: AgentManifest` (immutable for this version)
- `initialize(sdk, request) → AgentInitializationResult`
- `execute(request) → AgentExecutionResult`
- `cancel() → None`
- `health() → AgentHealth`

**Core-Side Implementations (`sdk/agent/adapters/`):**
- `ContextSDKImpl` — assembles context from Task + Execution
- `EventSDKImpl` — routes agent events through the Kernel with `AGENT_EVENT` taxonomy
- `ArtifactSDKImpl` — persists artifacts with SHA-256 content hashes and provenance
- `StateSDKImpl` — process-local; C4 replaces with durable state fabric
- `LoggingSDKImpl` — structlog with bound execution correlation
- `BenchmarkSDKImpl` — records benchmark metrics as structured logs
- `ModelSDKImpl` — **C1 stub** (raises `NotImplementedError` until C2)
- `ToolSDKImpl` — **C1 stub** (returns `DENIED` until C3)
- `MemorySDKImpl` — **C1 stub** (returns `[]` on retrieve; raises on write until C4)
- `VerificationSDKImpl` — **C1 stub** (records `INCONCLUSIVE` runs until C6)

**SDK Factory (`sdk/agent/runtime/build_agent_sdk`):**
The single place where Core wires its `Impl` classes to Protocol interfaces for a specific execution. Change the wiring here as later phases add real implementations; agent code never changes.

**AgentAdapter (`core/agents/adapter/AgentAdapter`) (C1 §16):**
Core's socket between the Kernel and any `DSRTAgent`. Enforces:
- `initialize()` must run before `execute()`
- `cancel()` before `execute()` returns a `CANCELLED` result without invoking the agent
- Uncaught agent exceptions during `initialize()` become `DSRTError`
- Uncaught agent exceptions during `execute()` become normalized `FAILED` results with `AGENT_EXECUTION_FAILED` error code
- `health()` exceptions are swallowed and reported as `unhealthy`

**Boundary Guarantees Enforced:**
- Agents receive `Protocol` interfaces only — they cannot import `core.storage`, `core.repositories`, `core.kernel`, or any provider SDK
- All SDK instances carry `sdk_version` + `contract_version` so agents can gate on compatibility
- Every SDK method is `async` — no blocking calls into Core
- Agent-emitted events are always wrapped in the `AGENT_EVENT` type with `source = "agent.<slug>"` so trajectory analysis can distinguish agent vs Core events
- Artifacts always record `agent_slug`, `agent_version_id`, and `execution_id` in their provenance


---

### C1.9 — Complete Core API & Integration

- **Artifacts API** (`core/api/routers/artifacts.py`):
  - `GET /api/v1/executions/{execution_id}/artifacts` — Retrieve all outputs of an execution.
  - `GET /api/v1/artifacts/{artifact_id}` — Retrieve specific artifact metadata and provenance.
- **API Surface Finalized**: The FastAPI app (`core/api/app.py`) now mounts all 7 canonical REST routers: `auth`, `capabilities`, `agents`, `tasks`, `executions`, `events`, and `artifacts`.


---

### C1.10 — Resource Controller & Cancellation Propagation

- **Resource Controller** (`core/kernel/resources.py`): Tracks runtime execution usage against configured `ResourceLimits`. Raises normalized `ResourceLimitError` when boundaries (model calls, tool calls, token limits) are breached.
- **Cancellation Manager** (`core/kernel/cancellation.py`): Maintains a distributed registry of `asyncio.Event` tokens bound to `execution_id`. Allows API requests to broadcast cancellation signals to running background loops.
- **Execution Kernel Updates**: 
  - Generates ResourceController instances bound to executions.
  - Intercepts `/cancel` REST requests, shifts status to `CANCELLING`, sets the cancellation token, and transitions to `CANCELLED`.
  - Cleans up cancellation tokens implicitly on terminal transitions (`COMPLETED`, `FAILED`, `CANCELLED`).


  ---

### C1.11 — Observability & Benchmark Hooks

- **Observability Middleware** (`core/observability/middleware.py`): Automatically assigns a unique `req_...` ULID to every HTTP request, tracking timing (`X-Process-Time`) and binding `request_id` context to the structured logger (`structlog`) for deep trace correlation.
- **Benchmark Hooks** (`sdk/agent/adapters/benchmark_adapter.py`): The agent `BenchmarkSDK` now emits durable `BENCHMARK_RECORD` events directly into the execution trajectory, allowing downstream C8 evaluators to consume arbitrary agent-measured metrics securely.
- **Execution Telemetry API** (`GET /api/v1/executions/{id}/telemetry`): A dedicated evaluation export endpoint assembling the Execution, Configuration Fingerprint, Event Trajectory, Artifacts, and Resource Usage records into a single Arena-ready JSON envelope (C1 §39-40).



---

### C1.12 — Reference Research Intelligence Agent v1.0

The first buildable DSRT Agent, proving the Agent Contract works end-to-end (C1 §54).

**Package:** `agents/research_intelligence/` (external to `core/` and `sdk/` — imports only from `sdk.agent` and `schemas.domain`).

**Structure (mirrors the Agent Package Standard):**
- `manifest.yaml` — machine-readable identity, capabilities, requirements, permissions
- `specification/` — MISSION, PROFESSIONAL_STANDARD, SCOPE, OUTPUT_STANDARD
- `ontology/` — entities.yaml, relationships.yaml, ontology.yaml
- `knowledge/` — evidence_strength.yaml
- `reasoning/` — decomposition.yaml, synthesis.yaml
- `workflows/` — standard_research.yaml
- `policies/` — evidence_policy.yaml, uncertainty_policy.yaml
- `runtime/` — `models.py`, `planner.py`, `analyzer.py`, `finalizer.py`, `agent.py`
- `verification/` — domain-specific `ResearchVerifier` (claim, citation, completeness, contradiction checks)
- `failures/` — catalogue.yaml, recovery.yaml
- `benchmarks/` — benchmark.yaml (registry for future C8 suites)
- `integration/` — `registration.py`, `compatibility.py`

**DSRTAgent implementation** (`agents/research_intelligence/runtime/agent.py`):
- `identity` / `manifest` loaded from `manifest.yaml` at import time
- `initialize()` binds the injected `DSRTAgentSDK`, checks contract compatibility, emits `AGENT_READY`
- `execute()` runs the deterministic research workflow:
  1. Understand objective (via `sdk.context.get()`)
  2. Plan questions (`ResearchPlanner`)
  3. Analyze evidence into claims + citations (`EvidenceAnalyzer`)
  4. Verify with `ResearchVerifier`
  5. Emit benchmark metrics via `sdk.benchmark.record()`
  6. Render Markdown report + persist via `sdk.artifacts.create()`
- `cancel()` sets the cooperative cancellation flag
- `health()` reports readiness and lifecycle state

**Zero Core imports.** The agent depends only on:
- `sdk.agent` (DSRTAgentSDK, contract types)
- `schemas.domain` (frozen data types)
- `pyyaml` (manifest parsing)

**Registration flow** (`agents/research_intelligence/integration/register_agent`):
- Registers every declared capability in the Capability Registry (idempotent)
- Registers the agent version in the Agent Registry (idempotent)

**Contract tests** (`tests/contract/test_agent_contract.py`):
- Identity, manifest, capability slugs, conservative permissions
- Health when uninitialized
- Execute-before-initialize returns `FAILED` with `AGENT_NOT_INITIALIZED`

**Golden E2E test** (`tests/integration/test_research_agent.py`):
- Registers the agent through the real Registry
- Creates a task + execution via the REST API
- Builds a live SDK, wraps agent in `AgentAdapter`, runs the full lifecycle
- Asserts the artifact is created and accessible via `/api/v1/artifacts/{id}`
- Asserts the execution telemetry captures every domain event (`AGENT_READY`, `RESEARCH_STARTED`, `RESEARCH_PLAN_CREATED`, `EVIDENCE_ANALYZED`, `RESEARCH_VERIFIED`, `RESEARCH_COMPLETED`) plus `BENCHMARK_RECORD`

**Result:** The DSRT Agent Contract is proven — an independently developed agent package plugs into the Core via only the SDK, produces observable trajectories, generates verifiable artifacts, and integrates cleanly with the Execution Kernel.


---

### C1.13 — Contract Test Suite & Golden Path E2E

**Reusable Contract Compliance Harness** (`tests/contract/harness.py`):
- `ContractComplianceSuite` — a base test class defining the 12 canonical DSRT Agent contract checks (C1, C2 … C12)
- Every future DSRT agent package can inherit this suite by providing a single `agent_factory` fixture and a `sample_input_payload` fixture
- `assert_dsrt_agent_protocol_compliance()` — ad-hoc structural check for the DSRTAgent protocol

**Contract Test Suite for Research Intelligence** (`tests/contract/test_agent_contract.py`):
- Inherits the full `ContractComplianceSuite` and applies all 12 checks
- Adds Research-specific structural checks (expected capabilities, conservative permissions)

**Compatibility Matrix Tests** (`tests/contract/test_compatibility_matrix.py`) — C1 §46, §51:
- Validates alignment across `CORE_VERSION`, `AGENT_CONTRACT_VERSION`, `SDK_VERSION`, and the agent's declared `minimum_core_version` + `contract_version`
- Runs `validate_compatibility()` from the agent's own compatibility module

**Golden Path End-to-End Test** (`tests/integration/test_golden_path.py`) — C1 §53, §63:
- Executes the full canonical pipeline purely through the REST API + public SDK (no internal shortcuts)
- Nine explicit checkpoints:
  0. Core health + correct versions
  1. Authenticated user context
  2. Agent + Capabilities registered
  3. Task created with structured input
  4. Execution created with configuration fingerprint
  5. Agent initialized + executed through the AgentAdapter
  6. Artifact persisted with SHA-256 hash + provenance
  7. Events persisted with monotonic sequence (C1 §31)
  8. Execution reaches COMPLETED terminal state
  9. Telemetry export contains full trajectory
- Additional cancellation propagation test (C1 §34) verifies User → Kernel → Adapter → CANCELLED path

**Impact:** Any future DSRT agent — `financial_intelligence`, `software_engineering`, `operations_intelligence`, etc. — can be certified C1-compliant by inheriting `ContractComplianceSuite` and passing the shared harness. The Golden Path test doubles as the canonical smoke test for every Core release.