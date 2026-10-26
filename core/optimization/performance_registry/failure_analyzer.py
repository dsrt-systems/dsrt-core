"""
Phase C11.2: Failure Mode & Vulnerability Analyzer

Categorizes execution error patterns, context sensitivities, and mitigations.
"""

from typing import Dict, List, Optional
from schemas.domain.performance_intelligence import (
    FailureCategory,
    FailureModeDetail,
    FailureAnalysisResult,
    PerformanceEvidence,
)


class FailureAnalyzer:
    """Analyzes error signatures to categorize failure modes and recommend mitigations."""

    MITIGATIONS: Dict[FailureCategory, str] = {
        FailureCategory.CONTEXT_OVERFLOW: "Recompile context, summarize prompt, or escalate to higher context window model.",
        FailureCategory.FORMAT_VIOLATION: "Enforce strict JSON schema validation and append structured format retry instructions.",
        FailureCategory.TIMEOUT: "Increase timeout bounds or decompose task into smaller sub-tasks.",
        FailureCategory.API_RATE_LIMIT: "Apply exponential backoff, circuit breaking, or route to fallback model provider.",
        FailureCategory.TOOL_FAILURE: "Verify tool payload schemas and switch to verified alternate tool definitions.",
        FailureCategory.REASONING_ERROR: "Enable amplification strategy (e.g. self-consistency or chain-of-thought).",
        FailureCategory.SYSTEM_ERROR: "Check infrastructure logs and retry execution.",
        FailureCategory.UNKNOWN: "Log full execution trace for manual diagnostic inspection.",
    }

    def categorize_error(self, error_type: Optional[str], error_message: Optional[str]) -> FailureCategory:
        if not error_type and not error_message:
            return FailureCategory.UNKNOWN

        combined = f"{error_type or ''} {error_message or ''}".lower()

        if any(k in combined for k in ["context", "token limit", "max tokens", "too long", "overflow"]):
            return FailureCategory.CONTEXT_OVERFLOW
        if any(k in combined for k in ["json", "format", "parse", "schema", "invalid output", "syntax"]):
            return FailureCategory.FORMAT_VIOLATION
        if any(k in combined for k in ["timeout", "timed out", "deadline"]):
            return FailureCategory.TIMEOUT
        if any(k in combined for k in ["429", "rate limit", "quota", "throttled"]):
            return FailureCategory.API_RATE_LIMIT
        if any(k in combined for k in ["tool", "function call", "action failed"]):
            return FailureCategory.TOOL_FAILURE
        if any(k in combined for k in ["reasoning", "logic", "hallucination", "assertion"]):
            return FailureCategory.REASONING_ERROR
        if any(k in combined for k in ["500", "502", "503", "connection", "server error"]):
            return FailureCategory.SYSTEM_ERROR

        return FailureCategory.UNKNOWN

    def analyze_failures(
        self,
        model_id: str,
        evidence_list: List[PerformanceEvidence],
    ) -> FailureAnalysisResult:
        total_executions = len(evidence_list)
        failures = [e for e in evidence_list if e.reliability_score < 0.99]
        total_failures = len(failures)

        if total_executions == 0 or total_failures == 0:
            return FailureAnalysisResult(
                model_id=model_id,
                total_executions=total_executions,
                total_failures=0,
                overall_failure_rate=0.0,
                breakdown=[],
                primary_vulnerability=None,
            )

        overall_failure_rate = total_failures / total_executions

        category_counts: Dict[FailureCategory, int] = {cat: 0 for cat in FailureCategory}
        category_latencies: Dict[FailureCategory, List[float]] = {cat: [] for cat in FailureCategory}
        category_triggers: Dict[FailureCategory, List[str]] = {cat: [] for cat in FailureCategory}

        for f in failures:
            cat = self.categorize_error(f.error_type, f.error_message)
            category_counts[cat] += 1
            category_latencies[cat].append(f.latency_ms)
            if f.error_message:
                category_triggers[cat].append(f.error_message[:100])

        breakdown: List[FailureModeDetail] = []
        for cat, count in category_counts.items():
            if count > 0:
                lats = category_latencies[cat]
                avg_lat = sum(lats) / len(lats) if lats else 0.0
                triggers = list(set(category_triggers[cat]))[:3]
                breakdown.append(
                    FailureModeDetail(
                        category=cat,
                        frequency=count,
                        percentage=round(count / total_failures, 4),
                        average_latency_ms=round(avg_lat, 2),
                        common_triggers=triggers,
                        recommended_mitigation=self.MITIGATIONS[cat],
                    )
                )

        breakdown.sort(key=lambda x: x.frequency, reverse=True)
        primary_vulnerability = breakdown[0].category if breakdown else None

        return FailureAnalysisResult(
            model_id=model_id,
            total_executions=total_executions,
            total_failures=total_failures,
            overall_failure_rate=round(overall_failure_rate, 4),
            breakdown=breakdown,
            primary_vulnerability=primary_vulnerability,
        )