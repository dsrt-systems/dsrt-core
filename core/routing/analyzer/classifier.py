# core/routing/analyzer/classifier.py
"""
C9 Task Classifier (§28).

Deterministic multi-label domain classification for routing context.
Uses keyword frequency scoring — no LLM call.
"""

from __future__ import annotations

from core.routing.contracts import TaskClassification
from core.routing.enums import TaskDomain


# ── Domain keyword weights ─────────────────────────────────────────
# Higher weight = stronger signal for that domain.

_DOMAIN_SIGNALS: dict[TaskDomain, dict[str, float]] = {
    TaskDomain.RESEARCH: {
        "research": 3.0, "investigate": 3.0, "study": 2.0,
        "survey": 2.0, "literature": 3.0, "evidence": 2.0,
        "academic": 3.0, "paper": 2.0, "findings": 2.0,
        "report": 1.5, "analysis": 1.0, "review": 1.5,
        "deep dive": 3.0, "meta-analysis": 3.0,
    },
    TaskDomain.CODING: {
        "code": 3.0, "program": 2.0, "implement": 2.5,
        "debug": 3.0, "refactor": 3.0, "function": 2.0,
        "class": 1.5, "api": 2.0, "script": 2.0,
        "software": 2.0, "build": 1.5, "deploy": 2.0,
        "compile": 3.0, "test": 1.0, "unit test": 3.0,
        "bug": 2.0, "error": 1.0, "fix": 1.5,
    },
    TaskDomain.DATA_ANALYSIS: {
        "data": 2.0, "dataset": 3.0, "statistics": 3.0,
        "csv": 3.0, "dataframe": 3.0, "aggregate": 2.5,
        "pivot": 3.0, "chart": 2.0, "analytics": 3.0,
        "regression": 3.0, "correlation": 3.0,
        "visualization": 2.0, "visualisation": 2.0,
        "analysis": 1.5, "report": 1.0,
    },
    TaskDomain.WRITING: {
        "write": 2.0, "draft": 3.0, "compose": 3.0,
        "essay": 3.0, "article": 2.5, "blog": 3.0,
        "content": 1.5, "story": 2.0, "copy": 2.0,
        "edit": 2.0, "proofread": 3.0, "rewrite": 3.0,
        "tone": 2.0, "style": 1.0, "report": 1.5,
    },
    TaskDomain.PLANNING: {
        "plan": 2.5, "strategy": 3.0, "roadmap": 3.0,
        "schedule": 3.0, "organise": 2.5, "organize": 2.5,
        "break down": 3.0, "decompose": 3.0, "milestone": 3.0,
        "timeline": 2.5, "sprint": 2.5, "backlog": 3.0,
    },
    TaskDomain.BROWSER_OPERATION: {
        "browse": 3.0, "navigate": 2.5, "scrape": 3.0,
        "click": 2.0, "form": 2.0, "website": 2.0,
        "web page": 2.5, "browser": 3.0, "login": 2.5,
        "fill": 1.5, "submit": 1.5, "screenshot": 2.0,
    },
    TaskDomain.DOCUMENT_PROCESSING: {
        "pdf": 3.0, "document": 2.0, "extract": 2.0,
        "parse": 2.5, "ocr": 3.0, "scan": 2.0,
        "convert": 2.0, "read file": 2.5, "docx": 3.0,
        "spreadsheet": 2.5, "excel": 3.0,
    },
    TaskDomain.MULTI_AGENT: {
        "multi-agent": 3.0, "delegate": 2.5,
        "collaborate": 2.0, "team": 1.5,
        "orchestrate": 2.5, "coordinate": 2.0,
    },
    TaskDomain.LONG_HORIZON: {
        "multi-step": 3.0, "long-running": 3.0,
        "complex workflow": 3.0, "end-to-end": 2.5,
        "multi-phase": 3.0, "pipeline": 2.5,
        "sequential": 2.0, "chained": 2.5,
    },
}


class TaskClassifier:
    """Deterministic multi-label task domain classifier (§28).

    Usage::

        classifier = TaskClassifier()
        result = classifier.classify("Research this company and write a report")
        assert result.primary_domain == TaskDomain.RESEARCH
    """

    def __init__(
        self,
        signals: dict[TaskDomain, dict[str, float]] | None = None,
        min_score: float = 1.0,
        secondary_threshold: float = 0.3,   # was 0.4
        max_secondary: int = 3,
    ) -> None:
        self._signals = signals or _DOMAIN_SIGNALS
        self._min_score = min_score
        self._secondary_threshold = secondary_threshold
        self._max_secondary = max_secondary

    def classify(self, description: str) -> TaskClassification:
        """Classify a task description into one or more domains."""
        text = description.lower()
        scores = self._score(text)

        if not scores:
            return TaskClassification(
                primary_domain=TaskDomain.GENERAL,
                confidence=0.5,
            )

        sorted_domains = sorted(scores, key=scores.get, reverse=True)  # type: ignore[arg-type]
        primary = sorted_domains[0]
        primary_score = scores[primary]

        # Secondary domains: must be >= threshold * primary score
        threshold = primary_score * self._secondary_threshold
        secondary = [
            d
            for d in sorted_domains[1:]
            if scores[d] >= max(self._min_score, threshold)
        ][: self._max_secondary]

        # Confidence: ratio of primary score to total
        total = sum(scores.values())
        confidence = min(1.0, primary_score / max(total, 1))

        return TaskClassification(
            primary_domain=primary,
            secondary_domains=secondary,
            confidence=round(confidence, 2),
        )

    def _score(self, text: str) -> dict[TaskDomain, float]:
        """Compute weighted keyword scores per domain."""
        scores: dict[TaskDomain, float] = {}
        for domain, keywords in self._signals.items():
            total = 0.0
            for keyword, weight in keywords.items():
                # Count occurrences (capped at 3 to avoid over-counting)
                count = min(text.count(keyword), 3)
                total += count * weight
            if total >= self._min_score:
                scores[domain] = total
        return scores