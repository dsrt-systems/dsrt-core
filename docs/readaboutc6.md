
# DSRT Core — Phase C6 Verification & Reliability Fabric v1.0

**Status:** Certified Complete (C6.1 → C6.11)
**Core Version:** `1.0.0`
**Database:** Supabase (Managed PostgreSQL 16 + `dsrt` schema)
**New Tables:** 9 (verification_policies, verification_checks, claims, claim_evidence, claim_verifications, evidence, reliability_incidents, c6_recovery_decisions, review_requests)
**Extended Tables:** 2 (verification_runs +5 cols, verification_results +6 cols)

---

## 1. Phase C6 Objective

Build the independent, policy-driven verification and reliability layer that determines whether an agent's work actually satisfies the defined requirements and evidence standards.

> **C5 asks: "Can DSRT complete the work?"**
> **C6 asks: "Can DSRT establish evidence that the work is acceptable?"**

These are **separate authorities**. The agent cannot mark its own result as verified.

---

## 2. Complete C6 Sub-Phase Summary

| Sub-Phase | Component | Key Deliverables |
|---|---|---|
| **C6.1** | Contracts & Schemas | 8 enums, 16 domain schemas, 7 API schemas, 12 ID prefixes |
| **C6.2** | Database | 9 new ORM models, 2 extended, Alembic migration |
| **C6.3** | Engine & Lifecycle | VerificationEngine, LifecycleManager, RequestProcessor |
| **C6.4** | Deterministic Checks | 8 check types: Schema, Artifact, Constraint, Completeness, State, Tool, ClaimEvidence, Citation |
| **C6.5** | Evidence & Claims | EvidenceStore, ProvenanceTracker, claim lifecycle, evidence linking |
| **C6.6** | Aggregation & Policies | VerificationAggregator (GATE/MUST/SHOULD/MAY), 5 builtin policies, risk-based rules |
| **C6.7** | Reliability & Recovery | IncidentManager (13 categories), FailureClassifier, C6RecoveryDecider |
| **C6.8** | Human Review | ReviewManager (7 states), ReviewWorkflow, decision → recovery mapping |
| **C6.9** | SDK, API & Events | VerificationSDK (3 methods), 8 REST endpoints, 14 C6 event types |
| **C6.10** | C5 Integration | NodeVerificationHook, VerificationSchedulerHook, VerificationReplanHook |
| **C6.11** | Certification | 80+ tests, verify_c6.py, readaboutc6.md |

---

## 3. Architecture

```
EXECUTION OUTPUT
      │
      ▼
VERIFICATION ENGINE (C6.3)
      │
      ├── Schema Check (C6.4)
      ├── Artifact Check (C6.4)
      ├── Constraint Check (C6.4)
      ├── Completeness Check (C6.4)
      ├── State Check (C6.4)
      ├── Tool Check (C6.4)
      ├── Claim Evidence Check (C6.4)
      └── Citation Check (C6.4)
      │
      ▼
AGGREGATOR (C6.6)
  GATE → MUST_PASS → SHOULD_PASS → MAY_PASS
      │
      ▼
VERIFICATION RESULT
  ├── PASSED
  ├── PASSED_WITH_WARNINGS
  ├── FAILED → Reliability Incident (C6.7) → Recovery Decision
  ├── INCONCLUSIVE → Human Review (C6.8)
  └── REVIEW_REQUIRED
```

---

## 4. Key Invariants

| # | Invariant | Enforcement |
|---|-----------|-------------|
| 1 | Agent cannot self-verify | `SDKVerificationResult` is frozen; engine is independent |
| 2 | No single quality score | Multi-dimensional `dimensions` dict |
| 3 | Deterministic first | All 8 checks are deterministic; no LLM calls |
| 4 | Policy-driven aggregation | GATE/MUST/SHOULD/MAY rules, not majority-vote |
| 5 | Bounded recovery loops | max_verification_attempts, max_recovery_cycles, max_replans |
| 6 | Uncertainty is explicit | `UncertaintyLevel` enum on every check |
| 7 | Confidence has provenance | `ConfidenceRecord.basis` explains why |
| 8 | 13-category taxonomy | IncidentCategory covers all failure types |
| 9 | Review is first-class | 7-state lifecycle, auditable |
| 10 | C5 hooks, not modifications | Integration via hook functions |

---

## 5. Verification Levels

| Level | What | Checks |
|-------|------|--------|
| 1 — Tool | Tool result validity | ToolCheck |
| 2 — Node | Node contract satisfaction | All checks |
| 3 — Agent | Professional result quality | Completeness, ClaimEvidence |
| 4 — Artifact | Structure and integrity | SchemaCheck, ArtifactCheck |
| 5 — Task | Objective satisfaction | Completeness, ConstraintCheck |
| 6 — Execution | Reliability and compliance | IncidentManager, StateCheck |

---

## 6. REST API

```
POST   /api/v1/verifications                          Create & run verification
GET    /api/v1/verifications/{id}                      Get verification run
GET    /api/v1/verifications/{id}/checks               Get check details
GET    /api/v1/executions/{id}/verification             List verifications
GET    /api/v1/claims/{id}                              Get claim
GET    /api/v1/claims/{id}/verification                 Get claim verification
POST   /api/v1/verifications/{id}/review                Request human review
GET    /api/v1/executions/{id}/incidents                List reliability incidents
```

---

## 7. Agent SDK

```python
# Request verification
result = await sdk.verification.verify(
    subject_id="art_1",
    policy_id="research_v1",
    subject_type="artifact",
    inputs={"output": report, "expected_schema": schema},
)
# result.status == "PASSED" | "FAILED" | "INCONCLUSIVE"
# result.dimensions == {"correctness": 1.0, "completeness": 0.8, ...}

# Attach evidence to a claim
evidence = await sdk.verification.attach_evidence(
    claim_id="clm_1",
    evidence_ref="https://example.com/source",
    source_type="web",
    extracted_content="Revenue is 10B",
)

# Check verification status
status = await sdk.verification.get_verification_status("vrn_1")
```

---

## 8. Built-in Policies

| Policy | Risk | Required Checks | Use Case |
|--------|------|----------------|----------|
| `minimal` | Low | Schema, Artifact | Quick validation |
| `standard` | Medium | + Constraints, Completeness | Default |
| `research_v1` | High | + Claims, Citations | Research reports |
| `software_v1` | Medium | Schema, Artifact, Constraints | Code artifacts |
| `data_v1` | Medium | + Completeness | Datasets |

---

## 9. Run Instructions

```powershell
# Verify C6 certification
python scripts/verify_c6.py

# Run C6 tests
python -m pytest tests/unit/test_c6_verification.py -v

# Full regression
python -m pytest tests/unit -q
```

---

## 10. What C6 Enables

```
THINK → PLAN → ACT → OBSERVE → REMEMBER → VERIFY → RECOVER → REPLAN → CONTINUE
```

DSRT now has **independent verification** — the system can determine whether its own work is acceptable, trigger recovery when it isn't, and escalate to humans when it can't decide.
```

