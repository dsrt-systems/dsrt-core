"""
Aggregation Rules (C6 §31-32).

Defines how individual check results are combined into a final verdict.
Rules are policy-driven, not hardcoded.

Rule semantics:
  MUST_PASS    — If this check fails, the entire verification fails.
  SHOULD_PASS  — If this check fails, the result is PASSED_WITH_WARNINGS.
  MAY_PASS     — Informational only. Failure does not affect the verdict.
  GATE         — Must pass before subsequent checks are evaluated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RuleAction(str, Enum):
    """How a check result affects the final verdict."""
    MUST_PASS = "MUST_PASS"
    SHOULD_PASS = "SHOULD_PASS"
    MAY_PASS = "MAY_PASS"
    GATE = "GATE"


@dataclass(frozen=True)
class AggregationRule:
    """Maps a check type to its aggregation weight and action."""
    check_type: str
    action: RuleAction = RuleAction.SHOULD_PASS
    weight: float = 1.0
    description: str = ""

    def __post_init__(self) -> None:
        if not (0.0 <= self.weight <= 1.0):
            raise ValueError(
                f"AggregationRule weight must be 0.0-1.0, got {self.weight}"
            )


# Default rules for common verification scenarios
DEFAULT_RULES: list[AggregationRule] = [
    AggregationRule("SCHEMA_VALID", RuleAction.MUST_PASS, 1.0,
                    "Output must conform to declared schema."),
    AggregationRule("ARTIFACT_INTEGRITY", RuleAction.MUST_PASS, 1.0,
                    "Artifact must be parseable and intact."),
    AggregationRule("CONSTRAINT_SATISFIED", RuleAction.MUST_PASS, 1.0,
                    "All declared constraints must be met."),
    AggregationRule("CLAIM_SUPPORTED", RuleAction.SHOULD_PASS, 0.9,
                    "Claims should have supporting evidence."),
    AggregationRule("CITATION_VALID", RuleAction.SHOULD_PASS, 0.8,
                    "Citations should reference valid sources."),
    AggregationRule("COMPLETENESS", RuleAction.SHOULD_PASS, 0.85,
                    "Output should cover all requirements."),
    AggregationRule("STATE_CONSISTENT", RuleAction.SHOULD_PASS, 0.7,
                    "Shared state should be consistent across nodes."),
    AggregationRule("TOOL_RESULT_VALID", RuleAction.SHOULD_PASS, 0.7,
                    "Tool results should be valid and usable."),
    AggregationRule("SEMANTIC_CORRECTNESS", RuleAction.MAY_PASS, 0.5,
                    "Semantic correctness is informational in v1."),
    AggregationRule("POLICY_COMPLIANT", RuleAction.MAY_PASS, 0.5,
                    "Policy compliance is informational in v1."),
]


def get_rules_for_risk_level(risk_level: str) -> list[AggregationRule]:
    """Return aggregation rules appropriate for a risk level (C6 §45)."""
    if risk_level == "low":
        return [r for r in DEFAULT_RULES if r.action == RuleAction.MUST_PASS]
    elif risk_level == "high":
        return list(DEFAULT_RULES)
    else:
        return [
            r for r in DEFAULT_RULES
            if r.action in (RuleAction.MUST_PASS, RuleAction.SHOULD_PASS)
        ]