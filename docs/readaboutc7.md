# DSRT Core — Phase C7 World Runtime v1.0

**Status:** Certified Complete (C7.1 → C7.10)
**Core Version:** `1.0.0`
**Database:** Supabase (Managed PostgreSQL 16 + `dsrt` schema)
**New Tables:** 6 (world_components, world_snapshots, world_state_versions, world_state_changes, world_network_policies, world_health_records)
**Extended Tables:** 1 (world_instances +3 C7 columns)
**Built-in Worlds:** 4 (Research v1, Research v2, Software Engineering, Data Science)

---

## 1. Phase C7 Objective

Build the persistent, isolated, reproducible, and observable World Runtime in which DSRT agents perform realistic work.

> **A World is the complete stateful environment against which an execution can be observed and evaluated.**

---

## 2. Sub-Phase Summary

| Sub-Phase | Component | Deliverables |
|---|---|---|
| C7.1 | Schemas | 5 enums, 16 events, 7 new schemas, extended WorldManifest |
| C7.2 | Database | 6 new ORM models, 3 extension columns, Alembic migration |
| C7.3 | Templates | Software, Research v2, DataScience worlds + 3 environments |
| C7.4 | Runtime | 15-state lifecycle, DSRTWorld protocol, WorldManager (8 ops) |
| C7.5 | Components | 5 types (Filesystem, Browser, Terminal, Runtime, Database) |
| C7.6 | State | WorldStateManager, SnapshotManager, DiffEngine |
| C7.7 | Isolation | 6 boundaries, 5 network modes, credential broker |
| C7.8 | SDK/API | WorldSDK (4 methods), 14 REST routes |
| C7.9 | Integration | WorldResolver (C5), WorldVerificationHook (C6) |
| C7.10 | Certification | 60+ tests, verify_c7.py, readaboutc7.md |

---

## 3. Architecture
```
USER → TASK → PLANNER → ORCHESTRATOR
│
┌─────────┴─────────┐
▼ ▼
AGENT WORLD
│ │
▼ ▼
MODEL ┌──────┴──────┐
│ ▼ ▼
▼ COMPONENTS STATE
TOOLS (5 types) (versioned)
│ │ │
└─────┬──────┘ │
▼ ▼
ISOLATION SNAPSHOTS
(6 layers) (3 types)
│ │
▼ ▼
CREDENTIALS DIFFS
(brokered) (reversible)

```

## 4. Key Invariants

| # | Invariant | Enforcement |
|---|-----------|-------------|
| 1 | Worlds isolated by default | `WorldIsolationManager.check_cross_world_access()` |
| 2 | Agents never access raw infra | `WorldSDK` is the only interface |
| 3 | State ≠ Agent state | Separate `WorldState` vs agent working memory |
| 4 | Credentials never exposed | `WorldCredentialBroker` injects, never reveals |
| 5 | All actions reversible-classified | `WorldActionReversibility` on every change |
| 6 | Snapshots are immutable | `WorldSnapshotORM` never updated |
| 7 | Network policy-driven | 5 modes, domain allow/deny, rate limiting |
| 8 | Lifecycle deterministic | 15-state machine with validated transitions |

---

## 5. Run Instructions

```powershell
python scripts/verify_c7.py
python -m pytest tests/unit/test_c7_worlds.py -v
python main.py
text

