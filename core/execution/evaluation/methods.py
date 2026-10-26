"""
Evaluation methods — Deterministic, Evidence-based, Rubric-based.

Each method is independently runnable and returns an EvaluationMethodResult.
The EvaluationEngine composes them; no method is mandatory for every task.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from core.execution.evaluation.contracts import (
    ConfidenceLevel,
    EvaluationCategory,
    EvaluationFinding,
    EvaluationInput,
    EvaluationLimitation,
    EvaluatorRef,
    NormalizedMetric,
    ScoreKind,
)


# ---------------------------------------------------------------------------
# Method result
# ---------------------------------------------------------------------------

class EvaluationMethodResult(BaseModel):
    """Output of a single evaluation method."""

    method: str  # DETERMINISTIC | EVIDENCE | RUBRIC
    evaluator: EvaluatorRef
    metrics: list[NormalizedMetric] = Field(default_factory=list)
    findings: list[EvaluationFinding] = Field(default_factory=list)
    limitations: list[EvaluationLimitation] = Field(default_factory=list)
    raw_details: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int = 0
    completed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Deterministic evaluator
# ---------------------------------------------------------------------------

class DeterministicEvaluator:
    """
    Deterministic checks:
    - execution status / reliability
    - exact or normalized text match against expected_output
    - JSON schema validation against expected_schema
    - constraint keyword presence
    - success-criteria coverage (substring / regex)
    - tool-result success flags

    All scores produced here are reliable numbers or booleans.
    """

    EVALUATOR = EvaluatorRef(
        evaluator_id="c10.deterministic",
        evaluator_version="1.0.0",
        evaluator_name="C10 Deterministic Evaluator",
        method="DETERMINISTIC",
        source="C10",
    )

    async def evaluate(self, inp: EvaluationInput) -> EvaluationMethodResult:
        metrics: list[NormalizedMetric] = []
        findings: list[EvaluationFinding] = []
        limitations: list[EvaluationLimitation] = []

        # --- Reliability / task success from execution status -------------
        status = (inp.execution_status or "").upper()
        succeeded = status in ("COMPLETED", "SUCCESS", "SUCCEEDED")
        metrics.append(
            NormalizedMetric(
                metric_id="reliability.execution_succeeded",
                name="Execution Succeeded",
                category=EvaluationCategory.RELIABILITY,
                score_kind=ScoreKind.BOOLEAN,
                boolean_value=succeeded,
                value=1.0 if succeeded else 0.0,
                min_value=0.0,
                max_value=1.0,
                confidence=ConfidenceLevel.HIGH,
                method="DETERMINISTIC",
            )
        )
        metrics.append(
            NormalizedMetric(
                metric_id="task_success.completed",
                name="Task Completed",
                category=EvaluationCategory.TASK_SUCCESS,
                score_kind=ScoreKind.BOOLEAN,
                boolean_value=succeeded and bool(inp.output_text or inp.output_structured),
                value=(
                    1.0
                    if succeeded and bool(inp.output_text or inp.output_structured)
                    else 0.0
                ),
                min_value=0.0,
                max_value=1.0,
                confidence=ConfidenceLevel.HIGH,
                method="DETERMINISTIC",
            )
        )
        if not succeeded:
            findings.append(
                EvaluationFinding(
                    category=EvaluationCategory.RELIABILITY,
                    severity="error",
                    summary=f"Execution status was '{inp.execution_status}'.",
                    detail="Task cannot be considered successful.",
                )
            )

        # --- Error presence -----------------------------------------------
        error_count = len(inp.errors)
        metrics.append(
            NormalizedMetric(
                metric_id="reliability.error_count",
                name="Error Count",
                category=EvaluationCategory.RELIABILITY,
                score_kind=ScoreKind.NUMERIC_UNBOUNDED,
                value=float(error_count),
                unit="count",
                confidence=ConfidenceLevel.HIGH,
                method="DETERMINISTIC",
            )
        )

        # --- Exact / normalized match -------------------------------------
        if inp.expected_output is not None:
            actual = (inp.output_text or "").strip()
            expected = inp.expected_output.strip()
            exact = actual == expected
            normalized = (
                re.sub(r"\s+", " ", actual).lower()
                == re.sub(r"\s+", " ", expected).lower()
            )
            metrics.append(
                NormalizedMetric(
                    metric_id="correctness.exact_match",
                    name="Exact Match",
                    category=EvaluationCategory.CORRECTNESS,
                    score_kind=ScoreKind.BOOLEAN,
                    boolean_value=exact,
                    value=1.0 if exact else 0.0,
                    min_value=0.0,
                    max_value=1.0,
                    confidence=ConfidenceLevel.HIGH,
                    method="DETERMINISTIC",
                )
            )
            metrics.append(
                NormalizedMetric(
                    metric_id="correctness.normalized_match",
                    name="Normalized Match",
                    category=EvaluationCategory.CORRECTNESS,
                    score_kind=ScoreKind.BOOLEAN,
                    boolean_value=normalized,
                    value=1.0 if normalized else 0.0,
                    min_value=0.0,
                    max_value=1.0,
                    confidence=ConfidenceLevel.HIGH,
                    method="DETERMINISTIC",
                )
            )
            if not normalized:
                findings.append(
                    EvaluationFinding(
                        category=EvaluationCategory.CORRECTNESS,
                        severity="warning",
                        summary="Output does not match expected value.",
                    )
                )
        else:
            limitations.append(
                EvaluationLimitation(
                    category=EvaluationCategory.CORRECTNESS,
                    reason="No expected_output provided; exact-match scoring skipped.",
                    impact="Do not claim numeric correctness from deterministic method alone.",
                )
            )

        # --- Schema validation --------------------------------------------
        if inp.expected_schema is not None:
            schema_ok, schema_detail = self._validate_schema(
                inp.output_structured, inp.expected_schema
            )
            metrics.append(
                NormalizedMetric(
                    metric_id="correctness.schema_valid",
                    name="Schema Valid",
                    category=EvaluationCategory.CORRECTNESS,
                    score_kind=ScoreKind.BOOLEAN,
                    boolean_value=schema_ok,
                    value=1.0 if schema_ok else 0.0,
                    min_value=0.0,
                    max_value=1.0,
                    confidence=ConfidenceLevel.HIGH,
                    method="DETERMINISTIC",
                    notes=schema_detail,
                )
            )
            if not schema_ok:
                findings.append(
                    EvaluationFinding(
                        category=EvaluationCategory.CORRECTNESS,
                        severity="error",
                        summary="Output failed schema validation.",
                        detail=schema_detail,
                    )
                )

        # --- Constraint adherence (keyword / phrase presence) -------------
        if inp.constraints:
            satisfied = 0
            for constraint in inp.constraints:
                present = self._constraint_satisfied(
                    constraint, inp.output_text or "", inp.output_structured
                )
                if present:
                    satisfied += 1
                else:
                    findings.append(
                        EvaluationFinding(
                            category=EvaluationCategory.CONSTRAINT_ADHERENCE,
                            severity="warning",
                            summary=f"Constraint not clearly satisfied: {constraint}",
                        )
                    )
            ratio = satisfied / len(inp.constraints)
            metrics.append(
                NormalizedMetric(
                    metric_id="constraints.satisfaction_ratio",
                    name="Constraint Satisfaction Ratio",
                    category=EvaluationCategory.CONSTRAINT_ADHERENCE,
                    score_kind=ScoreKind.NUMERIC_BOUNDED,
                    value=ratio,
                    min_value=0.0,
                    max_value=1.0,
                    confidence=ConfidenceLevel.MEDIUM,
                    method="DETERMINISTIC",
                    notes=(
                        "Heuristic presence check. Not a semantic proof of adherence."
                    ),
                )
            )
        else:
            limitations.append(
                EvaluationLimitation(
                    category=EvaluationCategory.CONSTRAINT_ADHERENCE,
                    reason="No constraints provided.",
                    impact="Constraint adherence cannot be scored.",
                )
            )

        # --- Success criteria coverage ------------------------------------
        if inp.success_criteria:
            hit = 0
            for criterion in inp.success_criteria:
                if self._criterion_met(criterion, inp.output_text or ""):
                    hit += 1
                else:
                    findings.append(
                        EvaluationFinding(
                            category=EvaluationCategory.COMPLETENESS,
                            severity="warning",
                            summary=f"Success criterion not met: {criterion}",
                        )
                    )
            ratio = hit / len(inp.success_criteria)
            metrics.append(
                NormalizedMetric(
                    metric_id="completeness.criteria_coverage",
                    name="Success Criteria Coverage",
                    category=EvaluationCategory.COMPLETENESS,
                    score_kind=ScoreKind.NUMERIC_BOUNDED,
                    value=ratio,
                    min_value=0.0,
                    max_value=1.0,
                    confidence=ConfidenceLevel.MEDIUM,
                    method="DETERMINISTIC",
                )
            )
        else:
            limitations.append(
                EvaluationLimitation(
                    category=EvaluationCategory.COMPLETENESS,
                    reason="No success_criteria provided.",
                    impact="Completeness cannot be deterministically scored.",
                )
            )

        # --- Tool execution -----------------------------------------------
        if inp.tool_results:
            tool_ok = sum(
                1 for t in inp.tool_results
                if t.get("success") is True or t.get("status") == "success"
            )
            total = len(inp.tool_results)
            metrics.append(
                NormalizedMetric(
                    metric_id="tool_execution.success_ratio",
                    name="Tool Execution Success Ratio",
                    category=EvaluationCategory.TOOL_EXECUTION,
                    score_kind=ScoreKind.NUMERIC_BOUNDED,
                    value=tool_ok / total,
                    min_value=0.0,
                    max_value=1.0,
                    confidence=ConfidenceLevel.HIGH,
                    method="DETERMINISTIC",
                )
            )
            if tool_ok < total:
                findings.append(
                    EvaluationFinding(
                        category=EvaluationCategory.TOOL_EXECUTION,
                        severity="warning",
                        summary=f"{total - tool_ok}/{total} tool calls did not succeed.",
                    )
                )
        else:
            limitations.append(
                EvaluationLimitation(
                    category=EvaluationCategory.TOOL_EXECUTION,
                    reason="No tool_results provided.",
                    impact="Tool execution quality not assessed.",
                )
            )

        # --- Verification results passthrough -----------------------------
        if inp.verification_results:
            ver_ok = sum(
                1 for v in inp.verification_results
                if v.get("passed") is True or v.get("status") == "passed"
            )
            total_v = len(inp.verification_results)
            metrics.append(
                NormalizedMetric(
                    metric_id="correctness.verification_pass_ratio",
                    name="Verification Pass Ratio",
                    category=EvaluationCategory.CORRECTNESS,
                    score_kind=ScoreKind.NUMERIC_BOUNDED,
                    value=ver_ok / total_v,
                    min_value=0.0,
                    max_value=1.0,
                    confidence=ConfidenceLevel.HIGH,
                    method="DETERMINISTIC",
                    evidence_refs=[
                        v.get("check_id", "") for v in inp.verification_results
                        if v.get("check_id")
                    ],
                )
            )

        return EvaluationMethodResult(
            method="DETERMINISTIC",
            evaluator=self.EVALUATOR,
            metrics=metrics,
            findings=findings,
            limitations=limitations,
        )

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _validate_schema(
        data: dict[str, Any] | None,
        schema: dict[str, Any],
    ) -> tuple[bool, str]:
        if data is None:
            return False, "No structured output provided for schema validation."

        # Minimal structural check: required keys + basic type matching.
        # Full JSON-Schema engines can replace this via C8 adapters later.
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        missing = [k for k in required if k not in data]
        if missing:
            return False, f"Missing required fields: {missing}"

        type_map = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "object": dict,
            "array": list,
        }
        for key, prop in properties.items():
            if key not in data:
                continue
            expected_type = prop.get("type")
            if expected_type and expected_type in type_map:
                if not isinstance(data[key], type_map[expected_type]):
                    return (
                        False,
                        f"Field '{key}' expected {expected_type}, "
                        f"got {type(data[key]).__name__}.",
                    )
        return True, "Schema validation passed."

    @staticmethod
    def _constraint_satisfied(
        constraint: str,
        text: str,
        structured: dict[str, Any] | None,
    ) -> bool:
        needle = constraint.strip().lower()
        if needle and needle in text.lower():
            return True
        if structured is not None:
            blob = json.dumps(structured, default=str).lower()
            if needle in blob:
                return True
        return False

    @staticmethod
    def _criterion_met(criterion: str, text: str) -> bool:
        """
        Support plain substring or /regex/ form.
        """
        c = criterion.strip()
        if len(c) >= 2 and c.startswith("/") and c.endswith("/"):
            try:
                return re.search(c[1:-1], text, re.IGNORECASE) is not None
            except re.error:
                return False
        return c.lower() in text.lower()


# ---------------------------------------------------------------------------
# Evidence evaluator
# ---------------------------------------------------------------------------

class EvidenceEvaluator:
    """
    Evidence-based checks:
    - presence and quality of cited sources / provenance
    - tool-result backing for claims
    - artifact availability
    - verification evidence linkage

    Produces numeric scores only where evidence density is measurable.
    Otherwise emits QUALITATIVE metrics + limitations.
    """

    EVALUATOR = EvaluatorRef(
        evaluator_id="c10.evidence",
        evaluator_version="1.0.0",
        evaluator_name="C10 Evidence Evaluator",
        method="EVIDENCE",
        source="C10",
    )

    async def evaluate(self, inp: EvaluationInput) -> EvaluationMethodResult:
        metrics: list[NormalizedMetric] = []
        findings: list[EvaluationFinding] = []
        limitations: list[EvaluationLimitation] = []

        # --- Artifact presence --------------------------------------------
        artifact_count = len(inp.artifact_refs)
        metrics.append(
            NormalizedMetric(
                metric_id="artifact_quality.count",
                name="Artifact Count",
                category=EvaluationCategory.ARTIFACT_QUALITY,
                score_kind=ScoreKind.NUMERIC_UNBOUNDED,
                value=float(artifact_count),
                unit="count",
                confidence=ConfidenceLevel.HIGH,
                method="EVIDENCE",
            )
        )
        if artifact_count == 0:
            findings.append(
                EvaluationFinding(
                    category=EvaluationCategory.ARTIFACT_QUALITY,
                    severity="info",
                    summary="No artifacts attached to this execution.",
                )
            )
            limitations.append(
                EvaluationLimitation(
                    category=EvaluationCategory.ARTIFACT_QUALITY,
                    reason="No artifacts to inspect.",
                    impact="Artifact quality cannot be graded beyond presence.",
                )
            )

        # --- Tool-backed evidence density ---------------------------------
        tool_results = inp.tool_results or []
        if tool_results:
            backed = sum(
                1 for t in tool_results
                if t.get("success") is True or t.get("status") == "success"
            )
            metrics.append(
                NormalizedMetric(
                    metric_id="evidence.tool_backed_ratio",
                    name="Tool-Backed Evidence Ratio",
                    category=EvaluationCategory.EVIDENCE_QUALITY,
                    score_kind=ScoreKind.NUMERIC_BOUNDED,
                    value=backed / len(tool_results),
                    min_value=0.0,
                    max_value=1.0,
                    confidence=ConfidenceLevel.HIGH,
                    method="EVIDENCE",
                )
            )
        else:
            limitations.append(
                EvaluationLimitation(
                    category=EvaluationCategory.EVIDENCE_QUALITY,
                    reason="No tool results available as evidence.",
                    impact=(
                        "Cannot claim tool-grounded evidence quality. "
                        "Do not invent an evidence score."
                    ),
                )
            )

        # --- Source / provenance citations in output ----------------------
        sources = self._extract_source_markers(inp.output_text or "")
        metrics.append(
            NormalizedMetric(
                metric_id="evidence.source_marker_count",
                name="Source Marker Count",
                category=EvaluationCategory.EVIDENCE_QUALITY,
                score_kind=ScoreKind.NUMERIC_UNBOUNDED,
                value=float(len(sources)),
                unit="count",
                confidence=ConfidenceLevel.MEDIUM,
                method="EVIDENCE",
                notes="Counts URL/citation-like markers; not semantic source validation.",
            )
        )
        if sources:
            findings.append(
                EvaluationFinding(
                    category=EvaluationCategory.EVIDENCE_QUALITY,
                    severity="info",
                    summary=f"Detected {len(sources)} source marker(s) in output.",
                    evidence_refs=sources[:10],
                )
            )
        else:
            findings.append(
                EvaluationFinding(
                    category=EvaluationCategory.EVIDENCE_QUALITY,
                    severity="info",
                    summary="No explicit source markers detected in output.",
                )
            )

        # --- Verification linkage -----------------------------------------
        if inp.verification_results:
            linked = sum(
                1 for v in inp.verification_results
                if v.get("evidence_ref") or v.get("artifact_ref")
            )
            metrics.append(
                NormalizedMetric(
                    metric_id="evidence.verification_linkage_ratio",
                    name="Verification Evidence Linkage",
                    category=EvaluationCategory.EVIDENCE_QUALITY,
                    score_kind=ScoreKind.NUMERIC_BOUNDED,
                    value=linked / len(inp.verification_results),
                    min_value=0.0,
                    max_value=1.0,
                    confidence=ConfidenceLevel.HIGH,
                    method="EVIDENCE",
                )
            )
        else:
            limitations.append(
                EvaluationLimitation(
                    category=EvaluationCategory.EVIDENCE_QUALITY,
                    reason="No verification_results to assess evidence linkage.",
                    impact="Evidence linkage ratio unavailable.",
                )
            )

        # --- Qualitative overall evidence note (NO fabricated score) ------
        metrics.append(
            NormalizedMetric(
                metric_id="evidence.overall_assessment",
                name="Overall Evidence Assessment",
                category=EvaluationCategory.EVIDENCE_QUALITY,
                score_kind=ScoreKind.QUALITATIVE,
                qualitative_value=self._qualitative_evidence_summary(
                    artifact_count=artifact_count,
                    tool_count=len(tool_results),
                    source_count=len(sources),
                    verification_count=len(inp.verification_results or []),
                ),
                confidence=ConfidenceLevel.MEDIUM,
                method="EVIDENCE",
                notes=(
                    "Qualitative summary only. No overall numeric evidence "
                    "score is produced because no single reliable scale applies."
                ),
            )
        )

        return EvaluationMethodResult(
            method="EVIDENCE",
            evaluator=self.EVALUATOR,
            metrics=metrics,
            findings=findings,
            limitations=limitations,
        )

    @staticmethod
    def _extract_source_markers(text: str) -> list[str]:
        urls = re.findall(r"https?://[^\s\]\)]+", text)
        citations = re.findall(r"\[\d+\]", text)
        return urls + citations

    @staticmethod
    def _qualitative_evidence_summary(
        *,
        artifact_count: int,
        tool_count: int,
        source_count: int,
        verification_count: int,
    ) -> str:
        parts = []
        if artifact_count:
            parts.append(f"{artifact_count} artifact(s)")
        if tool_count:
            parts.append(f"{tool_count} tool result(s)")
        if source_count:
            parts.append(f"{source_count} source marker(s)")
        if verification_count:
            parts.append(f"{verification_count} verification result(s)")
        if not parts:
            return "No supporting evidence attached to this execution."
        return "Evidence present: " + ", ".join(parts) + "."


# ---------------------------------------------------------------------------
# Rubric evaluator
# ---------------------------------------------------------------------------

class RubricCriterion(BaseModel):
    """One row in a qualitative rubric."""

    criterion_id: str
    category: EvaluationCategory
    name: str
    description: str = ""
    # Ordered labels low → high. No numeric mapping is applied unless
    # the caller explicitly provides weight + ordinal_scores.
    ordinal_labels: list[str] = Field(
        default_factory=lambda: ["poor", "fair", "good", "excellent"]
    )


class RubricDefinition(BaseModel):
    """A structured rubric for tasks without objective numeric answers."""

    rubric_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = "default"
    criteria: list[RubricCriterion] = Field(default_factory=list)
    # If False (default), never convert ordinal labels into floats.
    allow_numeric_mapping: bool = False
    ordinal_scores: dict[str, float] = Field(default_factory=dict)


DEFAULT_RUBRIC = RubricDefinition(
    rubric_id="c10.default_rubric",
    name="Default Qualitative Rubric",
    allow_numeric_mapping=False,
    criteria=[
        RubricCriterion(
            criterion_id="rubric.task_success",
            category=EvaluationCategory.TASK_SUCCESS,
            name="Task Success",
            description="Did the output address the requested task?",
        ),
        RubricCriterion(
            criterion_id="rubric.completeness",
            category=EvaluationCategory.COMPLETENESS,
            name="Completeness",
            description="Were all parts of the request covered?",
        ),
        RubricCriterion(
            criterion_id="rubric.correctness",
            category=EvaluationCategory.CORRECTNESS,
            name="Correctness",
            description="Is the content accurate to the extent assessable?",
        ),
        RubricCriterion(
            criterion_id="rubric.constraint_adherence",
            category=EvaluationCategory.CONSTRAINT_ADHERENCE,
            name="Constraint Adherence",
            description="Were stated constraints respected?",
        ),
        RubricCriterion(
            criterion_id="rubric.clarity",
            category=EvaluationCategory.ARTIFACT_QUALITY,
            name="Clarity / Usability",
            description="Is the deliverable clear and usable?",
        ),
    ],
)


class RubricEvaluator:
    """
    Rubric-based assessment for tasks without objectively measurable answers.

    Default behavior is QUALITATIVE / ORDINAL only. Numeric mapping is
    opt-in via RubricDefinition.allow_numeric_mapping and never happens
    silently — that would violate the critical scoring rule.
    """

    EVALUATOR = EvaluatorRef(
        evaluator_id="c10.rubric",
        evaluator_version="1.0.0",
        evaluator_name="C10 Rubric Evaluator",
        method="RUBRIC",
        source="C10",
    )

    def __init__(self, rubric: RubricDefinition | None = None) -> None:
        self._rubric = rubric or DEFAULT_RUBRIC

    async def evaluate(self, inp: EvaluationInput) -> EvaluationMethodResult:
        metrics: list[NormalizedMetric] = []
        findings: list[EvaluationFinding] = []
        limitations: list[EvaluationLimitation] = []

        if not (inp.output_text or inp.output_structured):
            limitations.append(
                EvaluationLimitation(
                    reason="No output available for rubric assessment.",
                    impact="All rubric criteria left unscored.",
                )
            )
            return EvaluationMethodResult(
                method="RUBRIC",
                evaluator=self.EVALUATOR,
                limitations=limitations,
            )

        for criterion in self._rubric.criteria:
            label = self._assess_criterion(criterion, inp)
            metric = NormalizedMetric(
                metric_id=criterion.criterion_id,
                name=criterion.name,
                category=criterion.category,
                score_kind=ScoreKind.ORDINAL,
                ordinal_value=label,
                qualitative_value=(
                    f"{criterion.name}: {label}. {criterion.description}"
                ),
                confidence=ConfidenceLevel.LOW,
                method="RUBRIC",
                notes=(
                    "Heuristic ordinal assessment. Not a substitute for "
                    "human review on high-stakes tasks."
                ),
            )

            # Numeric mapping ONLY when explicitly enabled on the rubric.
            if (
                self._rubric.allow_numeric_mapping
                and label in self._rubric.ordinal_scores
            ):
                metric.score_kind = ScoreKind.NUMERIC_BOUNDED
                metric.value = self._rubric.ordinal_scores[label]
                metric.min_value = min(self._rubric.ordinal_scores.values())
                metric.max_value = max(self._rubric.ordinal_scores.values())
                metric.confidence = ConfidenceLevel.LOW
                metric.notes += (
                    " Numeric mapping applied because rubric.allow_numeric_mapping=True."
                )

            metrics.append(metric)
            findings.append(
                EvaluationFinding(
                    category=criterion.category,
                    severity="info",
                    summary=f"{criterion.name} rated '{label}'.",
                    detail=criterion.description,
                )
            )

        # Always record that rubric scores are limited.
        limitations.append(
            EvaluationLimitation(
                reason=(
                    "Rubric assessment is heuristic and low-confidence. "
                    "It does not constitute objective ground truth."
                ),
                impact=(
                    "Do not use rubric ordinals alone to declare a universal "
                    "winner in comparisons without human review or stronger methods."
                ),
            )
        )

        # Safety / policy placeholder finding (no fabricated pass score)
        metrics.append(
            NormalizedMetric(
                metric_id="safety.policy_review_status",
                name="Safety / Policy Review Status",
                category=EvaluationCategory.SAFETY_AND_POLICY,
                score_kind=ScoreKind.QUALITATIVE,
                qualitative_value="not_reviewed",
                confidence=ConfidenceLevel.UNKNOWN,
                method="RUBRIC",
                notes="Automated safety review is not claimed by this evaluator.",
            )
        )

        return EvaluationMethodResult(
            method="RUBRIC",
            evaluator=self.EVALUATOR,
            metrics=metrics,
            findings=findings,
            limitations=limitations,
            raw_details={"rubric_id": self._rubric.rubric_id},
        )

    def _assess_criterion(
        self,
        criterion: RubricCriterion,
        inp: EvaluationInput,
    ) -> str:
        """
        Lightweight heuristic ordinal assignment.

        This is intentionally conservative. Production deployments should
        replace or augment this with C8 rubric evaluators or human review.
        """
        text = (inp.output_text or "").strip()
        labels = criterion.ordinal_labels
        if not text:
            return labels[0]  # poorest

        length = len(text)
        # Very rough signals — documented as heuristic in metric notes.
        if criterion.criterion_id.endswith("completeness"):
            if inp.success_criteria:
                hits = sum(
                    1 for c in inp.success_criteria
                    if c.lower() in text.lower()
                )
                ratio = hits / len(inp.success_criteria)
                return self._ratio_to_label(ratio, labels)
            return labels[min(2, len(labels) - 1)] if length > 100 else labels[1]

        if criterion.criterion_id.endswith("constraint_adherence"):
            if not inp.constraints:
                return labels[min(2, len(labels) - 1)]
            hits = sum(1 for c in inp.constraints if c.lower() in text.lower())
            return self._ratio_to_label(hits / len(inp.constraints), labels)

        if criterion.criterion_id.endswith("task_success"):
            if inp.execution_status.upper() not in ("COMPLETED", "SUCCESS", "SUCCEEDED"):
                return labels[0]
            return labels[min(2, len(labels) - 1)] if length > 20 else labels[1]

        # correctness / clarity defaults
        if length < 20:
            return labels[1] if len(labels) > 1 else labels[0]
        if length < 200:
            return labels[min(2, len(labels) - 1)]
        return labels[min(2, len(labels) - 1)]

    @staticmethod
    def _ratio_to_label(ratio: float, labels: list[str]) -> str:
        if not labels:
            return "unknown"
        if ratio >= 0.9:
            return labels[-1]
        if ratio >= 0.7:
            return labels[min(2, len(labels) - 1)]
        if ratio >= 0.4:
            return labels[min(1, len(labels) - 1)]
        return labels[0]