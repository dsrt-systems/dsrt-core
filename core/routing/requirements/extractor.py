"""
C9 Requirement Extractor (§6–7).

Converts task descriptions and metadata into structured
``TaskRequirements`` objects.  Deterministic — no LLM call.

Extraction strategy:
  1. Explicit requirements passed by the caller always win.
  2. Keyword / pattern matching infers capabilities and domain.
  3. Hints dict allows structured overrides.
"""

from __future__ import annotations

import re
from typing import Any

from core.routing.contracts import (
    CapabilityRequirement,
    QualityRequirements,
    ResourceConstraints,
    SecurityRequirements,
    TaskClassification,
    TaskRequirements,
)
from core.routing.enums import (
    CapabilityImportance,
    QualityLevel,
    TaskDomain,
)

_CAPABILITY_KEYWORDS: dict[str, list[str]] = {
    "web_search": ["search the web", "web search", "search online", "google", "look up", "find online", "internet search"],
    "web_research": ["research", "investigate", "deep dive", "literature review", "survey", "explore", "study"],
    "source_analysis": ["analyse source", "analyze source", "source analysis", "evaluate source", "compare sources", "cross-reference"],
    "evidence_synthesis": ["synthesise", "synthesize", "evidence synthesis", "combine findings", "integrate evidence", "consolidate", "evidence-backed", "evidence-based", "evidence based", "evidence backed"],
    "citation": ["citation", "cite", "references", "bibliography", "footnote", "attribution", "source link"],
    "report_generation": ["report", "write a report", "generate report", "produce report", "detailed report"],
    "code_generation": ["write code", "generate code", "implement", "program", "script", "function", "class", "refactor", "debug", "fix bug"],
    "code_review": ["review code", "code review", "audit code", "check code", "lint"],
    "data_analysis": ["analyse data", "analyze data", "data analysis", "statistical", "dataset", "csv", "dataframe", "pandas", "aggregate", "pivot"],
    "data_visualisation": ["chart", "graph", "plot", "visualise", "visualize", "dashboard", "figure"],
    "document_processing": ["pdf", "document", "extract text", "parse document", "ocr", "scan", "read file"],
    "writing": ["write", "draft", "compose", "essay", "article", "blog post", "content", "copywrite"],
    "planning": ["plan", "strategy", "roadmap", "schedule", "break down", "decompose", "outline"],
    "browser_operation": ["browse", "navigate", "click", "fill form", "scrape", "interact with website", "browser"],
    "long_context": ["long document", "large file", "entire book", "full codebase", "long context", "100k tokens"],
    "structured_output": ["json", "structured", "schema", "table", "csv output", "xml", "yaml output"],
    "vision": ["image", "photo", "picture", "screenshot", "visual", "diagram", "chart analysis", "vision"],
    "reasoning": ["reason", "think step by step", "logic", "deduce", "infer", "complex problem", "mathematical", "proof"],
    "tool_use": ["use tools", "call api", "execute command", "run script", "invoke function"],
}

_DOMAIN_KEYWORDS: dict[TaskDomain, list[str]] = {
    TaskDomain.RESEARCH: ["research", "investigate", "study", "survey", "literature", "evidence", "academic", "paper", "report", "analysis", "findings"],
    TaskDomain.CODING: ["code", "program", "implement", "debug", "refactor", "function", "class", "api", "script", "software", "build", "deploy"],
    TaskDomain.DATA_ANALYSIS: ["data", "dataset", "statistics", "csv", "dataframe", "aggregate", "pivot", "chart", "visualisation", "visualization", "analytics"],
    TaskDomain.WRITING: ["write", "draft", "compose", "essay", "article", "blog", "content", "story", "copy", "edit", "proofread"],
    TaskDomain.PLANNING: ["plan", "strategy", "roadmap", "schedule", "organise", "organize", "break down", "decompose"],
    TaskDomain.BROWSER_OPERATION: ["browse", "navigate", "scrape", "click", "form", "website", "web page", "browser"],
    TaskDomain.DOCUMENT_PROCESSING: ["pdf", "document", "extract", "parse", "ocr", "scan", "convert", "read file"],
    TaskDomain.LONG_HORIZON: ["multi-step", "long-running", "complex workflow", "end-to-end", "multi-phase", "pipeline"],
}

_WRITE_ACTION_KEYWORDS = ["send email", "post to", "upload", "write to", "delete", "update database", "modify", "create account", "submit form", "publish", "deploy"]
_SANDBOX_KEYWORDS = ["execute code", "run script", "shell", "terminal", "command line", "subprocess", "eval"]

class RequirementExtractor:
    def __init__(
        self,
        capability_keywords: dict[str, list[str]] | None = None,
        domain_keywords: dict[TaskDomain, list[str]] | None = None,
    ) -> None:
        self._cap_kw = capability_keywords or _CAPABILITY_KEYWORDS
        self._dom_kw = domain_keywords or _DOMAIN_KEYWORDS

    def extract(
        self,
        task_id: str,
        description: str,
        *,
        hints: dict[str, Any] | None = None,
        explicit_capabilities: list[CapabilityRequirement] | None = None,
        explicit_classification: TaskClassification | None = None,
        explicit_quality: QualityRequirements | None = None,
        explicit_resources: ResourceConstraints | None = None,
        explicit_security: SecurityRequirements | None = None,
        output_type: str | None = None,
        required_tools: list[str] | None = None,
        preferred_tools: list[str] | None = None,
    ) -> TaskRequirements:
        hints = hints or {}
        text = description.lower()

        classification = explicit_classification or self._classify(text, hints)
        capabilities = explicit_capabilities or self._extract_capabilities(text, hints)
        quality = explicit_quality or self._infer_quality(text, hints)
        resources = explicit_resources or self._infer_resources(hints)
        security = explicit_security or self._infer_security(text, hints)
        out = output_type or hints.get("output_type") or self._infer_output(text)

        reqs = TaskRequirements(
            task_id=task_id,
            description=description,
            classification=classification,
            capabilities=capabilities,
            quality=quality,
            resources=resources,
            security=security,
            output_type=out,
            required_tools=required_tools or hints.get("required_tools", []),
            preferred_tools=preferred_tools or hints.get("preferred_tools", []),
        )
        
        # Explicitly set metadata if present
        if hints.get("metadata"):
            reqs.metadata = hints.get("metadata", {})
            
        return reqs

    def _classify(self, text: str, hints: dict[str, Any]) -> TaskClassification:
        scores: dict[TaskDomain, int] = {}
        for domain, keywords in self._dom_kw.items():
            count = sum(1 for kw in keywords if kw in text)
            if count > 0:
                scores[domain] = count

        if not scores:
            return TaskClassification(primary_domain=TaskDomain.GENERAL, confidence=0.5)

        sorted_domains = sorted(scores, key=scores.get, reverse=True)
        primary = sorted_domains[0]
        secondary = [d for d in sorted_domains[1:] if scores[d] >= max(1, scores[primary] // 2)][:3]

        total = sum(scores.values())
        confidence = min(1.0, scores[primary] / max(total, 1))

        return TaskClassification(
            primary_domain=primary,
            secondary_domains=secondary,
            confidence=round(confidence, 2),
        )

    def _extract_capabilities(self, text: str, hints: dict[str, Any]) -> list[CapabilityRequirement]:
        caps: list[CapabilityRequirement] = []
        seen: set[str] = set()

        for cap_id, keywords in self._cap_kw.items():
            if any(kw in text for kw in keywords):
                caps.append(CapabilityRequirement(capability_id=cap_id, required=True, importance=CapabilityImportance.REQUIRED))
                seen.add(cap_id)

        for cap_id in hints.get("capabilities", []):
            if cap_id not in seen:
                caps.append(CapabilityRequirement(capability_id=cap_id, required=True, importance=CapabilityImportance.REQUIRED))
                seen.add(cap_id)

        for cap_id in hints.get("optional_capabilities", []):
            if cap_id not in seen:
                caps.append(CapabilityRequirement(capability_id=cap_id, required=False, importance=CapabilityImportance.OPTIONAL))
                seen.add(cap_id)

        return caps

    def _infer_quality(self, text: str, hints: dict[str, Any]) -> QualityRequirements:
        quality_str = hints.get("quality", "").lower()
        if "strict" in text or "strict" in quality_str:
            return QualityRequirements(overall=QualityLevel.STRICT, correctness=QualityLevel.STRICT, evidence_quality=QualityLevel.HIGH)
        if "high" in text or "high" in quality_str or "verified" in text:
            return QualityRequirements(overall=QualityLevel.HIGH, correctness=QualityLevel.HIGH, evidence_quality=QualityLevel.HIGH)
        if "minimum" in text or "quick" in text or "fast" in text:
            return QualityRequirements(overall=QualityLevel.MINIMUM, correctness=QualityLevel.STANDARD)
        return QualityRequirements()

    def _infer_resources(self, hints: dict[str, Any]) -> ResourceConstraints:
        return ResourceConstraints(
            max_cost_usd=hints.get("max_cost_usd"),
            max_duration_seconds=hints.get("max_duration_seconds"),
            max_input_tokens=hints.get("max_input_tokens"),
            max_output_tokens=hints.get("max_output_tokens"),
            max_total_tokens=hints.get("max_total_tokens"),
            max_tool_calls=hints.get("max_tool_calls"),
        )

    def _infer_security(self, text: str, hints: dict[str, Any]) -> SecurityRequirements:
        has_write = any(kw in text for kw in _WRITE_ACTION_KEYWORDS)
        needs_sandbox = any(kw in text for kw in _SANDBOX_KEYWORDS)

        return SecurityRequirements(
            external_write_actions=hints.get("external_write_actions", has_write),
            external_read_actions=hints.get("external_read_actions", True),
            requires_sandbox=hints.get("requires_sandbox", needs_sandbox),
            allowed_domains=hints.get("allowed_domains", []),
            max_privilege_level=hints.get("max_privilege_level", "standard"),
        )

    def _infer_output(self, text: str) -> str:
        if any(w in text for w in ["report", "document", "pdf"]): return "document"
        if any(w in text for w in ["code", "script", "function", "program"]): return "code"
        if any(w in text for w in ["json", "structured", "table", "csv"]): return "structured"
        if any(w in text for w in ["chart", "graph", "plot", "visual"]): return "visualisation"
        return "text"
