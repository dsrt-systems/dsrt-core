"""
Domain-Specific Research Verifier.

Runs deterministic policy checks over the research state. This is the AGENT's
verification logic. The Core Verification Fabric (C6) will add independent verification
above this layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agents.research_intelligence.runtime.models import ResearchState


@dataclass
class VerificationCheckResult:
    check: str
    passed: bool
    details: str = ""


@dataclass
class ResearchVerificationReport:
    status: str  # PASSED | PASSED_WITH_WARNINGS | FAILED
    checks: list[VerificationCheckResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


class ResearchVerifier:
    """Runs claim, citation, and completeness checks on ResearchState."""

    def verify(self, state: ResearchState) -> ResearchVerificationReport:
        report = ResearchVerificationReport(status="PASSED")

        self._check_plan_exists(state, report)
        self._check_claims_have_evidence(state, report)
        self._check_citations_well_formed(state, report)
        self._check_completeness(state, report)
        self._check_contradictions_preserved(state, report)

        if report.failures:
            report.status = "FAILED"
        elif report.warnings:
            report.status = "PASSED_WITH_WARNINGS"
        return report

    def _check_plan_exists(
        self, state: ResearchState, report: ResearchVerificationReport,
    ) -> None:
        passed = state.plan is not None and len(state.questions) > 0
        report.checks.append(
            VerificationCheckResult(
                check="plan_exists",
                passed=passed,
                details=f"{len(state.questions)} question(s) planned.",
            )
        )
        if not passed:
            report.failures.append("Research plan missing or empty.")

    def _check_claims_have_evidence(
        self, state: ResearchState, report: ResearchVerificationReport,
    ) -> None:
        unsupported = [c for c in state.claims if not c.evidence_ids]
        passed = not unsupported
        report.checks.append(
            VerificationCheckResult(
                check="claims_have_evidence",
                passed=passed,
                details=(
                    "All claims supported."
                    if passed
                    else f"{len(unsupported)} unsupported claim(s)."
                ),
            )
        )
        if unsupported:
            report.failures.append(
                f"Unsupported claims: {[c.id for c in unsupported]}"
            )

    def _check_citations_well_formed(
        self, state: ResearchState, report: ResearchVerificationReport,
    ) -> None:
        malformed = [
            c for c in state.citations
            if not (c.claim_id and c.evidence_id and c.source_id)
        ]
        passed = not malformed
        report.checks.append(
            VerificationCheckResult(
                check="citations_well_formed",
                passed=passed,
                details=(
                    "All citations reference claim/evidence/source."
                    if passed
                    else f"{len(malformed)} malformed citation(s)."
                ),
            )
        )
        if malformed:
            report.failures.append(
                f"Malformed citations: {[c.id for c in malformed]}"
            )

    def _check_completeness(
        self, state: ResearchState, report: ResearchVerificationReport,
    ) -> None:
        if state.unresolved_questions:
            report.warnings.append(
                f"Unresolved questions preserved: {state.unresolved_questions}"
            )
        report.checks.append(
            VerificationCheckResult(
                check="completeness",
                passed=True,
                details=(
                    f"{len(state.unresolved_questions)} unresolved "
                    f"of {len(state.questions)} questions."
                ),
            )
        )

    def _check_contradictions_preserved(
        self, state: ResearchState, report: ResearchVerificationReport,
    ) -> None:
        report.checks.append(
            VerificationCheckResult(
                check="contradictions_preserved",
                passed=True,
                details=f"{len(state.contradictions)} contradiction(s) recorded.",
            )
        )
        if state.contradictions:
            report.warnings.append(
                f"{len(state.contradictions)} contradiction(s) surfaced for review."
            )