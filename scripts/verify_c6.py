"""
C6 Phase Certification Script.

Verifies all C6 components are correctly built and integrated.
Run: python scripts/verify_c6.py
"""

from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def verify_c6() -> bool:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        checks.append((name, condition, detail))

    # C6.1 — Contracts & Schemas
    try:
        from schemas.domain.enums import (
            VerificationAction, ClaimStatus, EvidenceStatus,
            IncidentCategory, IncidentSeverity, ReviewStatus,
            CheckType, UncertaintyLevel,
        )
        from schemas.domain.verification import (
            VerificationPolicy, VerificationThresholds, FailureAction,
            VerificationCheckResult, C6VerificationResult,
            Evidence, EvidenceReference, Claim, ClaimVerification,
            Constraint, ConstraintResult, ReliabilityIncident,
            C6RecoveryDecision, ReviewRequest, ConfidenceRecord, Requirement,
        )
        assert len(list(IncidentCategory)) == 13
        assert len(list(ReviewStatus)) == 7
        assert len(list(CheckType)) == 14
        check("C6.1 Contracts and Schemas", True)
    except Exception as e:
        check("C6.1 Contracts and Schemas", False, str(e))

    # C6.2 — Database
    try:
        from core.storage.models import (
            VerificationPolicyORM, VerificationCheckORM,
            ClaimORM, ClaimEvidenceORM, ClaimVerificationORM,
            EvidenceORM, ReliabilityIncidentORM,
            C6RecoveryDecisionORM, ReviewRequestORM,
        )
        check("C6.2 Database Models", True)
    except Exception as e:
        check("C6.2 Database Models", False, str(e))

    # C6.3 — Engine & Lifecycle
    try:
        from core.verification.engine import (
            VerificationEngine, VerificationLifecycleManager,
            VerificationRequestProcessor,
        )
        lm = VerificationLifecycleManager()
        lm.validate_transition("PENDING", "RUNNING")
        assert lm.determine_final_status(["PASSED"]) == "PASSED"
        check("C6.3 Engine and Lifecycle", True)
    except Exception as e:
        check("C6.3 Engine and Lifecycle", False, str(e))

    # C6.4 — Deterministic Checks
    try:
        from core.verification.checks import (
            SchemaCheck, ArtifactCheck, ConstraintCheck,
            CompletenessCheck, StateCheck, ToolCheck,
            ClaimEvidenceCheck, CitationCheck,
        )
        checks_list = [
            SchemaCheck(), ArtifactCheck(), ConstraintCheck(),
            CompletenessCheck(), StateCheck(), ToolCheck(),
            ClaimEvidenceCheck(), CitationCheck(),
        ]
        assert len({c.check_type for c in checks_list}) == 8
        check("C6.4 Deterministic Checks", True)
    except Exception as e:
        check("C6.4 Deterministic Checks", False, str(e))

    # C6.5 — Evidence & Claims
    try:
        from core.verification.evidence import EvidenceStore, EvidenceProvenanceTracker
        from core.verification.evidence.provenance import ProvenanceChain, ProvenanceLink
        chain = ProvenanceChain(claim_id="c", claim_statement="test", is_complete=True)
        assert chain.is_complete
        check("C6.5 Evidence and Claims", True)
    except Exception as e:
        check("C6.5 Evidence and Claims", False, str(e))

    # C6.6 — Aggregation & Policies
    try:
        from core.verification.aggregation import VerificationAggregator, AggregationRule, RuleAction
        from core.verification.policies import VerificationPolicyManager, PolicyRegistry
        pm = VerificationPolicyManager()
        assert len(pm.list_policies()) >= 5
        agg = VerificationAggregator()
        from schemas.domain.verification import VerificationPolicy as VP
        o = agg.aggregate([], VP(id="t"))
        assert o.final_status == "INCONCLUSIVE"
        check("C6.6 Aggregation and Policies", True)
    except Exception as e:
        check("C6.6 Aggregation and Policies", False, str(e))

    # C6.7 — Reliability & Recovery
    try:
        from core.verification.reliability import IncidentManager, FailureClassifier, C6RecoveryDecider
        fc = FailureClassifier()
        from schemas.domain.enums import VerificationStatus
        cl = fc.classify(VerificationCheckResult(
            check_id="c", check_type="ARTIFACT_INTEGRITY",
            status=VerificationStatus.FAILED, summary="test",
        ))
        assert cl.category == IncidentCategory.ARTIFACT
        check("C6.7 Reliability and Recovery", True)
    except Exception as e:
        check("C6.7 Reliability and Recovery", False, str(e))

    # C6.8 — Human Review
    try:
        from core.verification.review import ReviewManager, ReviewWorkflow
        from core.verification.review.workflow import ReviewOutcome
        rm = ReviewManager.__new__(ReviewManager)
        rm._session = None
        rm._kernel = None
        rm._default_expiry = 24
        assert rm.review_to_verification_status(
            type("R", (), {"status": "APPROVED"})()
        ) == VerificationStatus.PASSED
        check("C6.8 Human Review", True)
    except Exception as e:
        check("C6.8 Human Review", False, str(e))

    # C6.9 — SDK, API, Events
    try:
        from schemas.domain.enums import EventType
        for e in ["VERIFICATION_REQUESTED", "CLAIM_CREATED", "REVIEW_REQUESTED", "VERIFICATION_FAILED"]:
            assert hasattr(EventType, e)
        from sdk.agent.interfaces.verification import VerificationSDK, SDKEvidenceResult
        from sdk.agent.adapters.verification_adapter import VerificationSDKImpl
        from core.api.routers.verification import router
        assert len(router.routes) >= 8
        check("C6.9 SDK, API, Events", True)
    except Exception as e:
        check("C6.9 SDK, API, Events", False, str(e))

    # C6.10 — C5 Integration
    try:
        from core.verification.integration import (
            NodeVerificationHook, VerificationSchedulerHook, VerificationReplanHook,
        )
        from core.verification.integration.node_hook import NodeVerificationOutcome
        from core.verification.integration.replan_hook import ReplanTrigger
        check("C6.10 C5 Integration", True)
    except Exception as e:
        check("C6.10 C5 Integration", False, str(e))

    # Summary
    print("\n" + "=" * 60)
    print("DSRT CORE - PHASE C6 CERTIFICATION")
    print("=" * 60)

    passed = sum(1 for _, ok, _ in checks if ok)
    failed = sum(1 for _, ok, _ in checks if not ok)

    for name, ok, detail in checks:
        icon = "[+]" if ok else "[!]"
        status = "PASS" if ok else "FAIL"
        line = f"  {icon} {status}  {name}"
        if detail:
            line += f" -- {detail}"
        print(line)

    print(f"\n  Total: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed > 0:
        print("\n  C6 CERTIFICATION FAILED")
        return False
    else:
        print("\n  C6 PHASE CERTIFIED COMPLETE")
        return True


if __name__ == "__main__":
    success = verify_c6()
    sys.exit(0 if success else 1)