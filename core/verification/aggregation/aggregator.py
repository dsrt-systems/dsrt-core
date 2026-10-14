"""
Verification Aggregator (C6 §31-32, §45-46).

Combines individual check results into a final verification verdict
using policy-driven rules. This is NOT majority-vote.

Aggregation logic (C6 §32):
  1. Evaluate GATE checks first — if any fail, stop and return FAILED
  2. Evaluate MUST_PASS checks — if any fail, result is FAILED
  3. Evaluate SHOULD_PASS checks — failures become warnings
  4. Evaluate MAY_PASS checks — informational only
  5. Compute multi-dimensional scores
  6. Determine final status

Example (C6 §32):
  Schema = PASS          (MUST_PASS)   → OK
  Evidence = PASS        (SHOULD_PASS) → OK
  Constraints = PASS     (MUST_PASS)   → OK
  Completeness = PASS    (SHOULD_PASS) → OK
  Semantic = INCONCLUSIVE (MAY_PASS)   → Warning only

  Result: PASSED_WITH_WARNINGS (not FAILED, not a single score)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from schemas.domain.enums import (
    CheckType,
    UncertaintyLevel,
    VerificationStatus,
)
from schemas.domain.verification import (
    C6VerificationResult,
    VerificationCheckResult,
    VerificationPolicy,
)

from core.observability.logging import get_logger
from core.verification.aggregation.rules import (
    AggregationRule,
    RuleAction,
    get_rules_for_risk_level,
)


logger = get_logger("dsrt.verification.aggregator")


@dataclass
class AggregationOutcome:
    """Intermediate result of the aggregation process."""
    final_status: str
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    gate_failures: list[str] = field(default_factory=list)
    dimensions: dict[str, float] = field(default_factory=dict)
    checks_evaluated: int = 0
    checks_passed: int = 0
    checks_failed: int = 0
    checks_skipped: int = 0
    reasoning: list[str] = field(default_factory=list)


class VerificationAggregator:
    """Policy-driven verification result aggregator (C6 §31-32).

    Usage:
        aggregator = VerificationAggregator()
        outcome = aggregator.aggregate(check_results, policy)
        # outcome.final_status == "PASSED_WITH_WARNINGS"
        # outcome.dimensions == {"correctness": 1.0, "completeness": 0.8, ...}
    """

    def __init__(
        self,
        custom_rules: list[AggregationRule] | None = None,
    ) -> None:
        self._custom_rules = custom_rules

    def aggregate(
        self,
        check_results: list[VerificationCheckResult],
        policy: VerificationPolicy,
    ) -> AggregationOutcome:
        """Aggregate check results into a final verdict (C6 §32).

        This is the core aggregation algorithm. It is deterministic
        and policy-driven — never majority-vote.

        Args:
            check_results: Individual check results from the engine.
            policy: The active verification policy.

        Returns:
            AggregationOutcome with final status, dimensions, and reasoning.
        """
        if not check_results:
            return AggregationOutcome(
                final_status=VerificationStatus.INCONCLUSIVE.value,
                reasoning=["No check results to aggregate."],
            )

        # 1. Resolve rules
        rules = self._resolve_rules(policy)
        rule_map = {r.check_type: r for r in rules}

        outcome = AggregationOutcome(
            final_status=VerificationStatus.PASSED.value,
        )

        # 2. Categorize checks by rule action
        must_pass_results: list[VerificationCheckResult] = []
        should_pass_results: list[VerificationCheckResult] = []
        may_pass_results: list[VerificationCheckResult] = []
        gate_results: list[VerificationCheckResult] = []
        unrated_results: list[VerificationCheckResult] = []

        for cr in check_results:
            outcome.checks_evaluated += 1
            rule = rule_map.get(cr.check_type)

            if rule:
                if rule.action == RuleAction.GATE:
                    gate_results.append(cr)
                elif rule.action == RuleAction.MUST_PASS:
                    must_pass_results.append(cr)
                elif rule.action == RuleAction.SHOULD_PASS:
                    should_pass_results.append(cr)
                elif rule.action == RuleAction.MAY_PASS:
                    may_pass_results.append(cr)
            else:
                # No rule for this check type — treat as SHOULD_PASS
                unrated_results.append(cr)
                should_pass_results.append(cr)

        # 3. Evaluate GATE checks first
        gate_failed = False
        for cr in gate_results:
            if cr.status == VerificationStatus.FAILED:
                gate_failed = True
                outcome.gate_failures.append(
                    f"GATE '{cr.check_type}': {cr.summary}"
                )
                outcome.checks_failed += 1
            elif self._is_pass(cr):
                outcome.checks_passed += 1

        if gate_failed:
            outcome.final_status = VerificationStatus.FAILED.value
            outcome.failures = outcome.gate_failures
            outcome.reasoning.append(
                "Gate check(s) failed. Remaining checks skipped."
            )
            outcome.checks_skipped = (
                len(must_pass_results)
                + len(should_pass_results)
                + len(may_pass_results)
            )
            outcome.dimensions = self._compute_dimensions(check_results)
            return outcome

        # 4. Evaluate MUST_PASS checks
        for cr in must_pass_results:
            if cr.status == VerificationStatus.FAILED:
                outcome.failures.append(
                    f"MUST_PASS '{cr.check_type}': {cr.summary}"
                )
                outcome.checks_failed += 1
            elif self._is_pass(cr):
                outcome.checks_passed += 1
            else:
                # INCONCLUSIVE on a MUST_PASS is a warning, not a failure
                outcome.warnings.append(
                    f"MUST_PASS '{cr.check_type}' is {cr.status.value}: "
                    f"{cr.summary}"
                )
                outcome.checks_passed += 1

        # 5. Evaluate SHOULD_PASS checks
        for cr in should_pass_results:
            if cr.status == VerificationStatus.FAILED:
                outcome.warnings.append(
                    f"SHOULD_PASS '{cr.check_type}': {cr.summary}"
                )
                outcome.checks_failed += 1
            elif self._is_pass(cr):
                outcome.checks_passed += 1
            else:
                outcome.warnings.append(
                    f"SHOULD_PASS '{cr.check_type}' is {cr.status.value}: "
                    f"{cr.summary}"
                )
                outcome.checks_passed += 1

        # 6. Evaluate MAY_PASS checks (informational)
        for cr in may_pass_results:
            if cr.status == VerificationStatus.FAILED:
                outcome.warnings.append(
                    f"[info] MAY_PASS '{cr.check_type}': {cr.summary}"
                )
            elif not self._is_pass(cr):
                outcome.warnings.append(
                    f"[info] MAY_PASS '{cr.check_type}' is {cr.status.value}"
                )
            outcome.checks_passed += 1  # MAY_PASS always counts as pass

        # 7. Determine final status
        if outcome.failures:
            # MUST_PASS or GATE failures → FAILED
            outcome.final_status = VerificationStatus.FAILED.value
            outcome.reasoning.append(
                f"{len(outcome.failures)} MUST_PASS check(s) failed."
            )
        elif outcome.warnings:
            # SHOULD_PASS failures → PASSED_WITH_WARNINGS
            outcome.final_status = VerificationStatus.PASSED_WITH_WARNINGS.value
            outcome.reasoning.append(
                f"{len(outcome.warnings)} warning(s) from SHOULD_PASS/MAY_PASS checks."
            )
        else:
            outcome.final_status = VerificationStatus.PASSED.value
            outcome.reasoning.append("All checks passed.")

        # 8. Check for INCONCLUSIVE results that need review
        inconclusive_count = sum(
            1 for cr in check_results
            if cr.status == VerificationStatus.INCONCLUSIVE
            and cr.required
        )
        if inconclusive_count > 0 and not outcome.failures:
            outcome.final_status = VerificationStatus.INCONCLUSIVE.value
            outcome.reasoning.append(
                f"{inconclusive_count} required check(s) inconclusive."
            )

        # 9. Compute multi-dimensional scores
        outcome.dimensions = self._compute_dimensions(check_results)

        logger.info(
            "aggregation_complete",
            final_status=outcome.final_status,
            checks_evaluated=outcome.checks_evaluated,
            checks_passed=outcome.checks_passed,
            checks_failed=outcome.checks_failed,
            failures=len(outcome.failures),
            warnings=len(outcome.warnings),
        )

        return outcome

    def to_verification_result(
        self,
        outcome: AggregationOutcome,
        check_results: list[VerificationCheckResult],
        policy: VerificationPolicy,
        verification_run_id: str,
    ) -> C6VerificationResult:
        """Convert an AggregationOutcome to a C6VerificationResult."""
        from datetime import datetime, timezone
        from core.storage.identifiers import IdPrefix, new_id

        return C6VerificationResult(
            id=new_id(IdPrefix.VERIFICATION_RESULT),
            verification_run_id=verification_run_id,
            status=VerificationStatus(outcome.final_status),
            checks=check_results,
            evidence_refs=[],
            failures=outcome.failures,
            warnings=outcome.warnings,
            required_actions=[],
            dimensions=outcome.dimensions,
            policy_id=policy.id,
            engine_version="1.0.0",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _resolve_rules(
        self, policy: VerificationPolicy,
    ) -> list[AggregationRule]:
        """Resolve aggregation rules from policy or defaults."""
        if self._custom_rules:
            return self._custom_rules

        # Use risk-level-based defaults
        return get_rules_for_risk_level(policy.risk_level)

    @staticmethod
    def _is_pass(cr: VerificationCheckResult) -> bool:
        """Check if a result counts as passing."""
        return cr.status in (
            VerificationStatus.PASSED,
            VerificationStatus.PASSED_WITH_WARNINGS,
        )

    @staticmethod
    def _compute_dimensions(
        check_results: list[VerificationCheckResult],
    ) -> dict[str, float]:
        """Compute multi-dimensional verification scores (C6 §5).

        Each dimension is independent. Never collapsed to one score.
        """
        dimensions: dict[str, float] = {}

        if not check_results:
            return dimensions

        # Group checks by dimension
        dimension_map: dict[str, list[VerificationCheckResult]] = {
            "correctness": [],
            "completeness": [],
            "evidence_quality": [],
            "integrity": [],
            "constraint_compliance": [],
            "consistency": [],
        }

        for cr in check_results:
            ct = cr.check_type
            if ct in (
                CheckType.SCHEMA_VALID.value,
                CheckType.SEMANTIC_CORRECTNESS.value,
            ):
                dimension_map["correctness"].append(cr)
            elif ct == CheckType.COMPLETENESS.value:
                dimension_map["completeness"].append(cr)
            elif ct in (
                CheckType.CLAIM_SUPPORTED.value,
                CheckType.CITATION_VALID.value,
                CheckType.CITATION_PRESENT.value,
                CheckType.SOURCE_ACCESSIBLE.value,
                CheckType.CONTRADICTION_CHECK.value,
            ):
                dimension_map["evidence_quality"].append(cr)
            elif ct in (
                CheckType.ARTIFACT_PARSEABLE.value,
                CheckType.ARTIFACT_INTEGRITY.value,
            ):
                dimension_map["integrity"].append(cr)
            elif ct == CheckType.CONSTRAINT_SATISFIED.value:
                dimension_map["constraint_compliance"].append(cr)
            elif ct == CheckType.STATE_CONSISTENT.value:
                dimension_map["consistency"].append(cr)

        def pass_rate(checks: list[VerificationCheckResult]) -> float:
            if not checks:
                return 1.0
            passed = sum(
                1 for c in checks
                if c.status in (
                    VerificationStatus.PASSED,
                    VerificationStatus.PASSED_WITH_WARNINGS,
                )
            )
            return round(passed / len(checks), 3)

        for dim, checks in dimension_map.items():
            if checks:
                dimensions[dim] = pass_rate(checks)

        # Overall pass rate (informational)
        dimensions["overall_pass_rate"] = pass_rate(check_results)

        return dimensions