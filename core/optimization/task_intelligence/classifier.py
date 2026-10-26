"""
Phase C11.1: Task Classifier Component

Implements classification routines for:
1. Domain Taxonomy (Software Engineering, Data Analysis, DevOps, etc.)
2. Intent Taxonomy (Code Generation, Refactoring, Reasoning, etc.)
3. Task Complexity Scoring (Multifactor score [0.0, 1.0] and categorical level)
4. Risk Profile Assessment (Security, Financial, Operational, Compliance, Reversibility)
"""

import re
from typing import Dict, List
from schemas.domain.task_intelligence import (
    TaskDomain,
    TaskIntent,
    TaskComplexityLevel,
    TaskComplexityScore,
    RiskLevel,
    TaskRiskProfile,
    TaskClassification,
)


class TaskClassifier:
    """Classifies domain, intent, complexity, and risk factors from task content."""

    DOMAIN_KEYWORDS: Dict[TaskDomain, List[str]] = {
        TaskDomain.SOFTWARE_ENGINEERING: [
            "function", "class", "def ", "class ", "import ", "code", "refactor",
            "bug", "patch", "api", "framework", "repo", "github", "compiler",
            "syntax", "async", "await", "test_", "unittest", "pytest"
        ],
        TaskDomain.DATA_ANALYSIS: [
            "dataframe", "pandas", "numpy", "csv", "sql", "query", "chart",
            "plot", "correlation", "regression", "metric", "dataset", "table",
            "statistics", "aggregate", "trend", "mean", "median", "variance"
        ],
        TaskDomain.CONTENT_GENERATION: [
            "draft", "article", "blog", "essay", "rewrite", "copywriting",
            "headline", "tone", "creative", "paraphrase", "summary", "style",
            "narrative", "grammar", "proofread"
        ],
        TaskDomain.RESEARCH_SYNTHESIS: [
            "research", "paper", "literature", "citations", "findings",
            "synthesize", "survey", "compare options", "pros and cons",
            "tradeoffs", "evidence", "hypothesis", "analysis of"
        ],
        TaskDomain.ADMINISTRATIVE: [
            "schedule", "calendar", "email", "meeting", "action items",
            "invoice", "format list", "organize notes", "spreadsheet",
            "agenda", "contact", "task list"
        ],
        TaskDomain.DEVOPS: [
            "docker", "kubernetes", "ci/cd", "pipeline", "bash", "powershell",
            "terraform", "deploy", "server", "aws", "gcp", "azure", "k8s",
            "container", "helm", "yaml", "nginx", "dns", "port"
        ],
    }

    INTENT_KEYWORDS: Dict[TaskIntent, List[str]] = {
        TaskIntent.CODE_GENERATION: [
            "write a function", "implement", "build script", "create class", "generate code"
        ],
        TaskIntent.BUG_FIXING: [
            "fix bug", "error", "traceback", "exception", "failing test", "issue", "debug", "nullpointer"
        ],
        TaskIntent.ARCHITECTURE_DESIGN: [
            "architecture", "system design", "component diagram", "design pattern", "schema design", "microservices"
        ],
        TaskIntent.REFACTORING: [
            "refactor", "clean up", "optimize structure", "simplify code", "reduce complexity", "rename"
        ],
        TaskIntent.DATA_EXTRACTION: [
            "extract json", "parse list", "scrape", "extract text", "parse fields", "regex match"
        ],
        TaskIntent.STATISTICAL_ANALYSIS: [
            "compute p-value", "statistical summary", "distribution", "variance", "std dev", "linear regression"
        ],
        TaskIntent.REASONING_INFERENCE: [
            "explain why", "deduce", "logically prove", "evaluate tradeoffs", "root cause", "derive"
        ],
        TaskIntent.SUMMARIZATION: [
            "summarize", "tl;dr", "key takeaways", "brief description", "abstract", "overview"
        ],
        TaskIntent.TRANSLATION: [
            "translate to", "convert python to rust", "port code", "convert language"
        ],
        TaskIntent.POLICY_COMPLIANCE: [
            "check compliance", "verify gdpr", "security audit", "policy rule", "check permission"
        ],
        TaskIntent.MULTIMODAL_PROCESSING: [
            "image analysis", "audio transcript", "ocr", "diagram render", "multimodal"
        ],
    }

    def classify_domain_and_intent(self, text: str, payload: Dict) -> TaskClassification:
        combined_content = (text + " " + str(payload)).lower()

        domain_scores: Dict[TaskDomain, float] = {
            d: 0.0 for d in TaskDomain if d != TaskDomain.MULTI_DOMAIN
        }
        for domain, keywords in self.DOMAIN_KEYWORDS.items():
            for kw in keywords:
                if kw in combined_content:
                    domain_scores[domain] += 1.0

        sorted_domains = sorted(domain_scores.items(), key=lambda x: x[1], reverse=True)
        top_domain, top_domain_score = sorted_domains[0]

        # Significant = keyword hit count >= 2. Competing = within 50% of the leader.
        significant_domains = [(d, s) for d, s in sorted_domains if s >= 2.0]

        secondary_domains: List[TaskDomain] = []
        if top_domain_score == 0:
            primary_domain = TaskDomain.SOFTWARE_ENGINEERING
        elif (
            len(significant_domains) >= 2
            and significant_domains[1][1] >= significant_domains[0][1] * 0.5
        ):
            # Two or more domains compete → multi-domain primary
            primary_domain = TaskDomain.MULTI_DOMAIN
            secondary_domains = [d for d, s in significant_domains]
        else:
            primary_domain = top_domain
            for d, score in sorted_domains[1:]:
                if score >= 2.0 and score >= top_domain_score * 0.5:
                    secondary_domains.append(d)

        intent_scores: Dict[TaskIntent, float] = {i: 0.0 for i in TaskIntent}
        for intent, keywords in self.INTENT_KEYWORDS.items():
            for kw in keywords:
                if kw in combined_content:
                    intent_scores[intent] += 1.0

        sorted_intents = sorted(intent_scores.items(), key=lambda x: x[1], reverse=True)
        top_intent, top_intent_score = sorted_intents[0]

        if top_intent_score == 0:
            if primary_domain == TaskDomain.SOFTWARE_ENGINEERING:
                primary_intent = TaskIntent.CODE_GENERATION
            elif primary_domain == TaskDomain.DATA_ANALYSIS:
                primary_intent = TaskIntent.STATISTICAL_ANALYSIS
            elif primary_domain == TaskDomain.RESEARCH_SYNTHESIS:
                primary_intent = TaskIntent.REASONING_INFERENCE
            else:
                primary_intent = TaskIntent.SUMMARIZATION
        else:
            primary_intent = top_intent

        secondary_intents = [
            i for i, score in sorted_intents[1:]
            if score >= 1.0 and score >= top_intent_score * 0.4
        ]

        total_hits = sum(domain_scores.values()) + sum(intent_scores.values())
        confidence = min(1.0, 0.5 + (total_hits * 0.05))

        return TaskClassification(
            primary_domain=primary_domain,
            secondary_domains=secondary_domains,
            primary_intent=primary_intent,
            secondary_intents=secondary_intents,
            confidence=round(confidence, 3),
        )

    def compute_complexity(self, text: str, payload: Dict) -> TaskComplexityScore:
        combined_text = text + " " + str(payload)

        length_factor = min(1.0, len(combined_text) / 5000.0)
        code_block_count = len(re.findall(r"```", combined_text)) / 2
        code_density = min(1.0, code_block_count * 0.25)

        reasoning_keywords = [
            "because", "therefore", "hypothesis", "verify",
            "tradeoff", "edge case", "proof", "optimizing",
        ]
        reasoning_count = sum(1 for kw in reasoning_keywords if kw in combined_text.lower())
        reasoning_steps = min(1.0, reasoning_count * 0.15)

        structural_breadth = min(1.0, len(payload.keys()) * 0.15) if payload else 0.1

        dep_count = 0
        if isinstance(payload, dict):
            steps = payload.get("steps") or payload.get("workflow") or payload.get("dependencies")
            if isinstance(steps, list):
                dep_count = len(steps)
        dependency_count_factor = min(1.0, dep_count * 0.2)

        sub_scores = {
            "context_length": round(length_factor, 3),
            "code_density": round(code_density, 3),
            "reasoning_steps": round(reasoning_steps, 3),
            "structural_breadth": round(structural_breadth, 3),
            "dependency_count": round(dependency_count_factor, 3),
        }

        overall_score = (
            0.25 * length_factor
            + 0.25 * code_density
            + 0.25 * reasoning_steps
            + 0.15 * structural_breadth
            + 0.10 * dependency_count_factor
        )
        overall_score = round(min(1.0, max(0.0, overall_score)), 3)

        if overall_score < 0.15:
            level = TaskComplexityLevel.TRIVIAL
        elif overall_score < 0.35:
            level = TaskComplexityLevel.LOW
        elif overall_score < 0.55:
            level = TaskComplexityLevel.MEDIUM
        elif overall_score < 0.75:
            level = TaskComplexityLevel.HIGH
        elif overall_score < 0.90:
            level = TaskComplexityLevel.VERY_HIGH
        else:
            level = TaskComplexityLevel.EXTREME

        explanation = (
            f"Task complexity evaluated as {level.value} (score: {overall_score}) "
            f"based on context volume, structural features, and reasoning intensity."
        )

        return TaskComplexityScore(
            score=overall_score,
            level=level,
            sub_scores=sub_scores,
            explanation=explanation,
        )

    def evaluate_risk(self, text: str, payload: Dict) -> TaskRiskProfile:
        combined_text = (text + " " + str(payload)).lower()

        sec_keywords = [
            "auth", "password", "secret", "private_key", "token", "eval(", "exec(",
            "sql injection", "vulnerability", "root", "sudo",
        ]
        fin_keywords = [
            "payment", "transfer", "stripe", "credit card", "billing",
            "refund", "financial", "wallet", "crypto",
        ]
        ops_keywords = [
            "drop table", "rm -rf", "delete", "format drive", "overwrite",
            "deploy prod", "restart server", "kill -9",
        ]
        comp_keywords = [
            "gdpr", "hipaa", "compliance", "pii", "soc2",
            "privacy policy", "personal data", "medical",
        ]

        sec_hits = [k for k in sec_keywords if k in combined_text]
        fin_hits = [k for k in fin_keywords if k in combined_text]
        ops_hits = [k for k in ops_keywords if k in combined_text]
        comp_hits = [k for k in comp_keywords if k in combined_text]

        sec_impact = min(1.0, len(sec_hits) * 0.4)
        fin_impact = min(1.0, len(fin_hits) * 0.4)
        ops_impact = min(1.0, len(ops_hits) * 0.5)
        comp_impact = min(1.0, len(comp_hits) * 0.4)

        reversibility = 1.0
        if ops_hits or "drop" in combined_text or "delete" in combined_text:
            reversibility = 0.2
        elif fin_hits:
            reversibility = 0.5

        hallucination_sensitivity = 0.5
        if sec_hits or comp_hits or fin_hits:
            hallucination_sensitivity = 0.9
        elif "exact" in combined_text or "fact" in combined_text:
            hallucination_sensitivity = 0.8

        high_risk_flags = []
        if sec_hits:
            high_risk_flags.append(
                f"Security indicators detected: {', '.join(sec_hits[:3])}"
            )
        if fin_hits:
            high_risk_flags.append(
                f"Financial indicators detected: {', '.join(fin_hits[:3])}"
            )
        if ops_hits:
            high_risk_flags.append(
                f"Destructive operational indicators detected: {', '.join(ops_hits[:3])}"
            )
        if comp_hits:
            high_risk_flags.append(
                f"Compliance/PII indicators detected: {', '.join(comp_hits[:3])}"
            )

        composite_risk_score = (
            0.35 * sec_impact
            + 0.25 * fin_impact
            + 0.25 * ops_impact
            + 0.15 * comp_impact
        )
        composite_risk_score = round(min(1.0, max(0.0, composite_risk_score)), 3)

        if composite_risk_score >= 0.7 or len(high_risk_flags) >= 3:
            overall_level = RiskLevel.CRITICAL
        elif composite_risk_score >= 0.4 or len(high_risk_flags) >= 2:
            overall_level = RiskLevel.HIGH
        elif composite_risk_score >= 0.15 or len(high_risk_flags) >= 1:
            overall_level = RiskLevel.MEDIUM
        else:
            overall_level = RiskLevel.LOW

        return TaskRiskProfile(
            overall_level=overall_level,
            score=composite_risk_score,
            security_impact=round(sec_impact, 3),
            financial_impact=round(fin_impact, 3),
            operational_impact=round(ops_impact, 3),
            compliance_impact=round(comp_impact, 3),
            reversibility=round(reversibility, 3),
            hallucination_sensitivity=round(hallucination_sensitivity, 3),
            high_risk_flags=high_risk_flags,
        )