"""
Comprehensive C6 Verification & Reliability Fabric Tests.

Covers all C6 sub-phases:
  C6.3 Engine + Lifecycle
  C6.4 Deterministic Checks (8 types)
  C6.5 Evidence + Claims
  C6.6 Aggregation + Policies
  C6.7 Reliability + Recovery
  C6.8 Human Review
  C6.9 SDK + Events
  C6.10 C5 Integration
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from schemas.domain.enums import (
    CheckType,
    ClaimStatus,
    EvidenceStatus,
    IncidentCategory,
    IncidentSeverity,
    ReviewStatus,
    UncertaintyLevel,
    VerificationAction,
    VerificationStatus,
)
from schemas.domain.verification import (
    C6RecoveryDecision,
    C6VerificationResult,
    Claim,
    ConfidenceRecord,
    Evidence,
    FailureAction,
    Requirement,
    VerificationCheckResult,
    VerificationPolicy,
    VerificationRequest,
    VerificationThresholds,
)


# =====================================================================
# C6.3 — Engine & Lifecycle
# =====================================================================


class TestVerificationLifecycle:
    def test_valid_transitions(self):
        from core.verification.engine.lifecycle import VerificationLifecycleManager
        lm = VerificationLifecycleManager()
        lm.validate_transition("PENDING", "RUNNING")
        lm.validate_transition("RUNNING", "PASSED")
        lm.validate_transition("RUNNING", "FAILED")
        lm.validate_transition("RUNNING", "INCONCLUSIVE")
        lm.validate_transition("RUNNING", "REVIEW_REQUIRED")
        lm.validate_transition("FAILED", "RUNNING")
        lm.validate_transition("INCONCLUSIVE", "REVIEW_REQUIRED")
        lm.validate_transition("REVIEW_REQUIRED", "PASSED")
        lm.validate_transition("REVIEW_REQUIRED", "FAILED")

    def test_invalid_transitions(self):
        from core.verification.engine.lifecycle import VerificationLifecycleManager
        lm = VerificationLifecycleManager()
        for invalid in [("PASSED", "RUNNING"), ("PENDING", "PASSED"), ("RUNNING", "PENDING")]:
            with pytest.raises(ValueError):
                lm.validate_transition(invalid[0], invalid[1])

    def test_terminal_states(self):
        from core.verification.engine.lifecycle import VerificationLifecycleManager
        lm = VerificationLifecycleManager()
        assert lm.is_terminal("PASSED")
        assert lm.is_terminal("PASSED_WITH_WARNINGS")
        assert not lm.is_terminal("RUNNING")
        assert not lm.is_terminal("FAILED")

    def test_determine_final_status(self):
        from core.verification.engine.lifecycle import VerificationLifecycleManager
        lm = VerificationLifecycleManager()
        assert lm.determine_final_status(["PASSED", "PASSED"]) == "PASSED"
        assert lm.determine_final_status(["PASSED", "FAILED"]) == "FAILED"
        assert lm.determine_final_status(["PASSED"], has_warnings=True) == "PASSED_WITH_WARNINGS"
        assert lm.determine_final_status(["INCONCLUSIVE"]) == "INCONCLUSIVE"
        assert lm.determine_final_status(["PASSED"], requires_review=True) == "REVIEW_REQUIRED"

    def test_retry_logic(self):
        from core.verification.engine.lifecycle import VerificationLifecycleManager
        lm = VerificationLifecycleManager()
        assert lm.can_retry("FAILED", 1, 3)
        assert lm.can_retry("INCONCLUSIVE", 2, 3)
        assert not lm.can_retry("FAILED", 3, 3)
        assert not lm.can_retry("PASSED", 1, 3)


class TestVerificationRequestProcessor:
    def test_valid_request(self):
        from core.verification.engine.request import VerificationRequestProcessor
        req = VerificationRequest(
            subject_type="artifact", subject_id="art_1", policy_id="test",
        )
        processed = VerificationRequestProcessor.process(req)
        assert processed.subject_type == "artifact"
        assert processed.inputs == {}

    def test_invalid_subject_type(self):
        from core.verification.engine.request import VerificationRequestProcessor
        from core.api.errors.exceptions import ValidationError
        req = VerificationRequest(
            subject_type="invalid_type", subject_id="x", policy_id="p",
        )
        with pytest.raises(ValidationError):
            VerificationRequestProcessor.validate(req)


class TestVerificationEngine:
    def test_construction(self):
        from core.verification.engine.engine import VerificationEngine
        engine = VerificationEngine.__new__(VerificationEngine)
        engine._checks = {}
        engine._session = None
        engine._kernel = None
        assert engine.get_registered_checks() == []

    def test_dimension_computation(self):
        from core.verification.engine.engine import VerificationEngine
        engine = VerificationEngine.__new__(VerificationEngine)
        engine._session = None
        engine._kernel = None
        results = [
            VerificationCheckResult(check_id="c1", check_type="SCHEMA_VALID", status=VerificationStatus.PASSED),
            VerificationCheckResult(check_id="c2", check_type="COMPLETENESS", status=VerificationStatus.FAILED),
            VerificationCheckResult(check_id="c3", check_type="CITATION_VALID", status=VerificationStatus.PASSED),
        ]
        dims = engine._compute_dimensions(results)
        assert dims["correctness"] == 1.0
        assert dims["completeness"] == 0.0
        assert dims["evidence_quality"] == 1.0


# =====================================================================
# C6.4 — Deterministic Checks
# =====================================================================


class TestDeterministicChecks:
    @pytest.fixture
    def policy(self):
        return VerificationPolicy(id="test")

    def test_schema_pass(self, policy):
        from core.verification.checks.schema_check import SchemaCheck
        sc = SchemaCheck()
        r = asyncio.run(sc.execute("artifact", "a1", {
            "output": {"name": "test", "value": 42},
            "expected_schema": {
                "type": "object",
                "required": ["name", "value"],
                "properties": {"name": {"type": "string"}, "value": {"type": "number"}},
            },
        }, policy))
        assert r.status == VerificationStatus.PASSED

    def test_schema_fail_missing_field(self, policy):
        from core.verification.checks.schema_check import SchemaCheck
        sc = SchemaCheck()
        r = asyncio.run(sc.execute("artifact", "a2", {
            "output": {"name": "test"},
            "expected_schema": {"type": "object", "required": ["name", "value"]},
        }, policy))
        assert r.status == VerificationStatus.FAILED

    def test_artifact_pass(self, policy):
        from core.verification.checks.artifact_check import ArtifactCheck
        ac = ArtifactCheck()
        r = asyncio.run(ac.execute("artifact", "a3", {
            "artifact": {"content": "Hello", "mime_type": "text/markdown", "size_bytes": 5},
        }, policy))
        assert r.status == VerificationStatus.PASSED

    def test_constraint_pass(self, policy):
        from core.verification.checks.constraint_check import ConstraintCheck
        cc = ConstraintCheck()
        r = asyncio.run(cc.execute("e", "e1", {
            "constraints": [{"field": "cost", "operator": "<=", "expected": 5.0}],
            "actual_values": {"cost": 2.5},
        }, policy))
        assert r.status == VerificationStatus.PASSED

    def test_constraint_fail(self, policy):
        from core.verification.checks.constraint_check import ConstraintCheck
        cc = ConstraintCheck()
        r = asyncio.run(cc.execute("e", "e2", {
            "constraints": [{"field": "cost", "operator": "<=", "expected": 1.0}],
            "actual_values": {"cost": 5.0},
        }, policy))
        assert r.status == VerificationStatus.FAILED

    def test_completeness(self, policy):
        from core.verification.checks.completeness_check import CompletenessCheck
        comp = CompletenessCheck()
        r = asyncio.run(comp.execute("t", "t1", {
            "requirements": [{"id": "r1", "description": "Market size", "priority": "required", "keywords": ["market"]}],
            "output": "The market is large.",
        }, policy))
        assert r.status in (VerificationStatus.PASSED, VerificationStatus.PASSED_WITH_WARNINGS)

    def test_state_consistency(self, policy):
        from core.verification.checks.state_check import StateCheck
        stc = StateCheck()
        r = asyncio.run(stc.execute("s", "s1", {
            "state": {"x": 1}, "expected_fields": ["x"],
        }, policy))
        assert r.status == VerificationStatus.PASSED

    def test_tool_results(self, policy):
        from core.verification.checks.tool_check import ToolCheck
        tc = ToolCheck()
        r = asyncio.run(tc.execute("t", "t1", {
            "tool_results": [{"tool_slug": "web", "status": "SUCCESS", "output": "data"}],
        }, policy))
        assert r.status == VerificationStatus.PASSED

    def test_tool_short_output_valid(self, policy):
        """Short output like '42', 'OK', 'true' must not trigger false warnings."""
        from core.verification.checks.tool_check import ToolCheck
        tc = ToolCheck()
        for short in ["42", "OK", "true", "0"]:
            r = asyncio.run(tc.execute("t", "t1", {
                "tool_results": [{"tool_slug": "x", "status": "SUCCESS", "output": short}],
            }, policy))
            assert r.status == VerificationStatus.PASSED, f"Failed for '{short}'"

    def test_tool_falsy_output_valid(self, policy):
        """0 and False are legitimate tool outputs."""
        from core.verification.checks.tool_check import ToolCheck
        tc = ToolCheck()
        r = asyncio.run(tc.execute("t", "t1", {
            "tool_results": [{"tool_slug": "count", "status": "SUCCESS", "output": 0}],
        }, policy))
        assert r.status == VerificationStatus.PASSED

    def test_claim_evidence(self, policy):
        from core.verification.checks.claim_check import ClaimEvidenceCheck
        cec = ClaimEvidenceCheck()
        r = asyncio.run(cec.execute("c", "c1", {
            "claims": [{"id": "c1", "source_refs": ["e1"]}],
            "evidence": [{"id": "e1"}],
            "contradictions": [],
        }, policy))
        assert r.status == VerificationStatus.PASSED

    def test_citation(self, policy):
        from core.verification.checks.citation_check import CitationCheck
        cic = CitationCheck()
        r = asyncio.run(cic.execute("c", "c1", {
            "citations": [{"id": "ci1", "source_ref": "url"}],
            "sources": [{"id": "s1", "url": "url"}],
        }, policy))
        assert r.status == VerificationStatus.PASSED

    def test_all_check_types_registered(self):
        from core.verification.checks import (
            SchemaCheck, ArtifactCheck, ConstraintCheck,
            CompletenessCheck, StateCheck, ToolCheck,
            ClaimEvidenceCheck, CitationCheck,
        )
        checks = [
            SchemaCheck(), ArtifactCheck(), ConstraintCheck(),
            CompletenessCheck(), StateCheck(), ToolCheck(),
            ClaimEvidenceCheck(), CitationCheck(),
        ]
        types = {c.check_type for c in checks}
        assert "SCHEMA_VALID" in types
        assert "ARTIFACT_INTEGRITY" in types
        assert "CONSTRAINT_SATISFIED" in types
        assert "COMPLETENESS" in types
        assert "STATE_CONSISTENT" in types
        assert "TOOL_RESULT_VALID" in types
        assert "CLAIM_SUPPORTED" in types
        assert "CITATION_VALID" in types
        assert len(types) == 8


# =====================================================================
# C6.6 — Aggregation & Policies
# =====================================================================


class TestAggregation:
    def test_all_pass(self):
        from core.verification.aggregation import VerificationAggregator
        agg = VerificationAggregator()
        p = VerificationPolicy(id="test", risk_level="medium")
        results = [
            VerificationCheckResult(check_id="c1", check_type="SCHEMA_VALID", status=VerificationStatus.PASSED),
            VerificationCheckResult(check_id="c2", check_type="ARTIFACT_INTEGRITY", status=VerificationStatus.PASSED),
        ]
        o = agg.aggregate(results, p)
        assert o.final_status == "PASSED"

    def test_must_pass_failure(self):
        from core.verification.aggregation import VerificationAggregator
        agg = VerificationAggregator()
        p = VerificationPolicy(id="test", risk_level="medium")
        results = [
            VerificationCheckResult(check_id="c1", check_type="SCHEMA_VALID", status=VerificationStatus.FAILED),
        ]
        o = agg.aggregate(results, p)
        assert o.final_status == "FAILED"

    def test_should_pass_warning(self):
        from core.verification.aggregation import VerificationAggregator
        agg = VerificationAggregator()
        p = VerificationPolicy(id="test", risk_level="medium")
        results = [
            VerificationCheckResult(check_id="c1", check_type="SCHEMA_VALID", status=VerificationStatus.PASSED),
            VerificationCheckResult(check_id="c2", check_type="ARTIFACT_INTEGRITY", status=VerificationStatus.PASSED),
            VerificationCheckResult(check_id="c3", check_type="COMPLETENESS", status=VerificationStatus.FAILED),
        ]
        o = agg.aggregate(results, p)
        assert o.final_status == "PASSED_WITH_WARNINGS"

    def test_empty_inconclusive(self):
        from core.verification.aggregation import VerificationAggregator
        agg = VerificationAggregator()
        p = VerificationPolicy(id="test")
        o = agg.aggregate([], p)
        assert o.final_status == "INCONCLUSIVE"

    def test_gate_blocks_remaining(self):
        from core.verification.aggregation import VerificationAggregator, AggregationRule, RuleAction
        custom = [AggregationRule("SCHEMA_VALID", RuleAction.GATE)]
        agg = VerificationAggregator(custom_rules=custom)
        p = VerificationPolicy(id="test")
        results = [
            VerificationCheckResult(check_id="c1", check_type="SCHEMA_VALID", status=VerificationStatus.FAILED),
            VerificationCheckResult(check_id="c2", check_type="COMPLETENESS", status=VerificationStatus.PASSED),
        ]
        o = agg.aggregate(results, p)
        assert o.final_status == "FAILED"
        assert o.checks_skipped > 0

    def test_risk_based_rules(self):
        from core.verification.aggregation.rules import get_rules_for_risk_level
        low = get_rules_for_risk_level("low")
        med = get_rules_for_risk_level("medium")
        high = get_rules_for_risk_level("high")
        assert len(low) < len(med) < len(high)

    def test_builtin_policies(self):
        from core.verification.policies.policy import VerificationPolicyManager
        pm = VerificationPolicyManager()
        assert pm.resolve("minimal") is not None
        assert pm.resolve("standard") is not None
        assert pm.resolve("research_v1") is not None
        assert pm.resolve("software_v1") is not None
        assert pm.resolve("data_v1") is not None
        assert pm.resolve("nonexistent") is None

    def test_policy_merge(self):
        from core.verification.policies.policy import VerificationPolicyManager
        pm = VerificationPolicyManager()
        merged = pm.merge_policies(pm.resolve("minimal"), pm.resolve("research_v1"))
        assert "SCHEMA_VALID" in merged.required_checks
        assert "CLAIM_SUPPORTED" in merged.required_checks
        assert merged.risk_level == "high"

    def test_no_single_score(self):
        """C6 §5: Dimensions must be independent, never collapsed."""
        from core.verification.aggregation import VerificationAggregator
        agg = VerificationAggregator()
        p = VerificationPolicy(id="test", risk_level="high")
        results = [
            VerificationCheckResult(check_id="c1", check_type="SCHEMA_VALID", status=VerificationStatus.PASSED),
            VerificationCheckResult(check_id="c2", check_type="COMPLETENESS", status=VerificationStatus.FAILED),
        ]
        o = agg.aggregate(results, p)
        assert "correctness" in o.dimensions
        assert "completeness" in o.dimensions
        assert "overall_pass_rate" in o.dimensions
        # No single "quality_score" key
        assert "quality_score" not in o.dimensions


# =====================================================================
# C6.7 — Reliability & Recovery
# =====================================================================


class TestReliability:
    def test_classify_artifact(self):
        from core.verification.reliability.classifier import FailureClassifier
        fc = FailureClassifier()
        cr = VerificationCheckResult(
            check_id="c1", check_type="ARTIFACT_INTEGRITY",
            status=VerificationStatus.FAILED, summary="Checksum mismatch",
        )
        cl = fc.classify(cr)
        assert cl.category == IncidentCategory.ARTIFACT
        assert cl.severity == IncidentSeverity.HIGH

    def test_classify_security(self):
        from core.verification.reliability.classifier import FailureClassifier
        fc = FailureClassifier()
        cr = VerificationCheckResult(
            check_id="c1", check_type="POLICY_COMPLIANT",
            status=VerificationStatus.FAILED, summary="Permission denied",
            details={"error_code": "PERMISSION_DENIED"},
        )
        cl = fc.classify(cr)
        assert cl.category == IncidentCategory.SECURITY
        assert cl.suggested_action == "STOP"

    def test_classify_error_code(self):
        from core.verification.reliability.classifier import FailureClassifier
        fc = FailureClassifier()
        cl = fc.classify_error_code("PROVIDER_TIMEOUT", "Model timed out")
        assert cl.category == IncidentCategory.PROVIDER
        assert cl.suggested_action == "RETRY"

    def test_13_categories(self):
        assert len(list(IncidentCategory)) == 13

    def test_recovery_accept_on_pass(self):
        from core.verification.reliability.recovery import C6RecoveryDecider, RecoveryContext
        decider = C6RecoveryDecider()
        result = C6VerificationResult(
            id="vr_1", verification_run_id="vrn_1",
            status=VerificationStatus.PASSED,
            checks=[], failures=[], warnings=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        ctx = RecoveryContext(verification_result=result, policy=VerificationPolicy(id="t"), execution_id="e")
        d = decider.decide(ctx)
        assert d.action == VerificationAction.ACCEPT

    def test_recovery_max_attempts(self):
        from core.verification.reliability.recovery import C6RecoveryDecider, RecoveryContext
        decider = C6RecoveryDecider()
        result = C6VerificationResult(
            id="vr_2", verification_run_id="vrn_2",
            status=VerificationStatus.FAILED,
            checks=[VerificationCheckResult(check_id="c1", check_type="TOOL_RESULT_VALID", status=VerificationStatus.FAILED)],
            failures=["TOOL_RESULT_VALID: timeout"], warnings=[],
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        )
        ctx = RecoveryContext(
            verification_result=result,
            policy=VerificationPolicy(id="t", thresholds=VerificationThresholds(max_verification_attempts=2)),
            execution_id="e", attempt_number=3,
        )
        d = decider.decide(ctx)
        assert d.action == VerificationAction.HUMAN_REVIEW
        assert not d.retry_allowed

    def test_recovery_security_stop(self):
        from core.verification.reliability.recovery import C6RecoveryDecider, RecoveryContext
        decider = C6RecoveryDecider()
        result = C6VerificationResult(
            id="vr_3", verification_run_id="vrn_3",
            status=VerificationStatus.FAILED,
            checks=[VerificationCheckResult(check_id="c1", check_type="POLICY_COMPLIANT", status=VerificationStatus.FAILED, details={"error_code": "PERMISSION_DENIED"})],
            failures=["POLICY_COMPLIANT: denied"], warnings=[],
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        )
        ctx = RecoveryContext(verification_result=result, policy=VerificationPolicy(id="t"), execution_id="e")
        d = decider.decide(ctx)
        assert d.action == VerificationAction.STOP

    def test_recovery_escalation(self):
        from core.verification.reliability.recovery import C6RecoveryDecider, RecoveryContext
        decider = C6RecoveryDecider()
        result = C6VerificationResult(
            id="vr_4", verification_run_id="vrn_4",
            status=VerificationStatus.FAILED,
            checks=[VerificationCheckResult(check_id="c1", check_type="TOOL_RESULT_VALID", status=VerificationStatus.FAILED)],
            failures=["TOOL_RESULT_VALID: timeout"], warnings=[],
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        )
        ctx = RecoveryContext(
            verification_result=result, policy=VerificationPolicy(id="t"),
            execution_id="e", attempt_number=2, previous_actions=["RETRY"],
        )
        d = decider.decide(ctx)
        assert d.action != VerificationAction.RETRY  # Escalated


# =====================================================================
# C6.8 — Human Review
# =====================================================================


class TestHumanReview:
    def test_review_states(self):
        states = [s.value for s in ReviewStatus]
        assert len(states) == 7
        for s in ["REQUESTED", "ASSIGNED", "IN_REVIEW", "APPROVED", "REJECTED", "RETURNED_FOR_REWORK", "EXPIRED"]:
            assert s in states

    def test_status_mapping(self):
        from core.verification.review.requests import ReviewManager
        mgr = ReviewManager.__new__(ReviewManager)
        mgr._session = None
        mgr._kernel = None
        mgr._default_expiry = 24
        assert mgr.review_to_verification_status(type("R", (), {"status": "APPROVED"})()) == VerificationStatus.PASSED
        assert mgr.review_to_verification_status(type("R", (), {"status": "REJECTED"})()) == VerificationStatus.FAILED
        assert mgr.review_to_verification_status(type("R", (), {"status": "EXPIRED"})()) == VerificationStatus.INCONCLUSIVE

    def test_decision_to_recovery(self):
        from core.verification.review.workflow import ReviewWorkflow
        assert ReviewWorkflow._decision_to_recovery("APPROVED") == VerificationAction.ACCEPT
        assert ReviewWorkflow._decision_to_recovery("REJECTED") == VerificationAction.REGENERATE
        assert ReviewWorkflow._decision_to_recovery("RETURNED_FOR_REWORK") == VerificationAction.RESEARCH_MORE


# =====================================================================
# C6.9 — SDK & Events
# =====================================================================


class TestC6SDKAndEvents:
    def test_c6_event_types(self):
        from schemas.domain.enums import EventType
        for e in [
            "VERIFICATION_REQUESTED", "VERIFICATION_CHECK_STARTED",
            "CLAIM_CREATED", "CLAIM_VERIFIED", "EVIDENCE_ATTACHED",
            "RELIABILITY_INCIDENT_CREATED", "REVIEW_REQUESTED",
            "VERIFICATION_FAILED",
        ]:
            assert hasattr(EventType, e)

    def test_verification_sdk_protocol(self):
        from sdk.agent.interfaces.verification import VerificationSDK
        assert hasattr(VerificationSDK, "verify")
        assert hasattr(VerificationSDK, "attach_evidence")
        assert hasattr(VerificationSDK, "get_verification_status")

    def test_sdk_impl_methods(self):
        from sdk.agent.adapters.verification_adapter import VerificationSDKImpl
        impl = VerificationSDKImpl.__new__(VerificationSDKImpl)
        impl._session = None
        impl._execution_id = "exe"
        impl._kernel = None
        impl._engine = None
        impl._evidence_store = None
        assert hasattr(impl, "verify")
        assert hasattr(impl, "attach_evidence")


# =====================================================================
# C6.10 — C5 Integration
# =====================================================================


class TestC5Integration:
    def test_node_hook_construction(self):
        from core.verification.integration.node_hook import NodeVerificationHook, NodeVerificationOutcome
        hook = NodeVerificationHook.__new__(NodeVerificationHook)
        hook._session = None
        hook._kernel = None
        hook._default_policy_id = "standard"
        assert hasattr(hook, "verify_node")
        o = NodeVerificationOutcome(
            node_key="n", node_execution_id="nex", verified=True,
            verification_status="PASSED",
        )
        assert o.verified
        assert not o.should_block_downstream

    def test_scheduler_hook(self):
        from core.verification.integration.scheduler_hook import VerificationSchedulerHook, SchedulingSignal
        s = SchedulingSignal(
            node_key="n", node_execution_id="nex",
            verification_passed=True, verification_status="PASSED",
            should_unblock_downstream=True,
        )
        assert s.should_unblock_downstream

    def test_replan_hook(self):
        from core.verification.integration.replan_hook import VerificationReplanHook, ReplanTrigger
        t = ReplanTrigger(
            should_replan=True, reason="test",
            failed_node_keys=["n"], recovery_action="RESEARCH_MORE",
        )
        assert t.should_replan


# =====================================================================
# C6 Architectural Invariants
# =====================================================================


class TestC6Invariants:
    def test_agent_cannot_self_verify(self):
        """C6 §13: The VerificationSDK.verify() delegates to the engine,
        not to the agent itself. The agent receives the result but
        cannot modify it."""
        from sdk.agent.interfaces.verification import SDKVerificationResult
        r = SDKVerificationResult(
            subject_id="art_1", policy_id="p", status="FAILED",
        )
        # SDKVerificationResult is frozen — agent cannot mutate it
        with pytest.raises(AttributeError):
            r.status = "PASSED"  # type: ignore

    def test_uncertainty_explicit(self):
        """C6 §33: Uncertainty is explicit, not a hidden number."""
        levels = [u.value for u in UncertaintyLevel]
        assert "CERTAIN" in levels
        assert "UNCERTAIN" in levels
        assert "CONTRADICTED" in levels
        assert "UNKNOWN" in levels

    def test_confidence_has_provenance(self):
        """C6 §34: Confidence must explain why."""
        c = ConfidenceRecord(
            basis=["source_count", "agreement"],
            generated_by="verifier_v1",
            policy_id="research_v1",
            value=0.87,
        )
        assert len(c.basis) > 0
        assert c.generated_by != ""

    def test_no_single_quality_score(self):
        """C6 §5, §60: No single collapsed score."""
        from core.verification.aggregation import VerificationAggregator
        agg = VerificationAggregator()
        p = VerificationPolicy(id="t", risk_level="high")
        results = [
            VerificationCheckResult(check_id="c1", check_type="SCHEMA_VALID", status=VerificationStatus.PASSED),
        ]
        o = agg.aggregate(results, p)
        assert "quality_score" not in o.dimensions
        assert "overall_pass_rate" in o.dimensions  # Informational, not authoritative