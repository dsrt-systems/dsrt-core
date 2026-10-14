"""
Constraint Verification Check (C6 §22).

Validates that execution constraints were satisfied.
Deterministic — evaluates constraint expressions against actual values.

Expected inputs:
  - inputs["constraints"]: list of constraint dicts, each with:
      - "type": "temporal" | "budget" | "policy" | "schema" | "custom"
      - "field": the field to check
      - "operator": "==" | "!=" | ">" | "<" | ">=" | "<=" | "in" | "contains"
      - "expected": the expected value
  - inputs["actual_values"]: dict mapping field names to actual values
"""

from __future__ import annotations

from typing import Any

from schemas.domain.enums import CheckType
from schemas.domain.verification import VerificationPolicy

from core.verification.checks.base import BaseCheck


class ConstraintCheck(BaseCheck):
    """Validates execution constraints (C6 §22)."""

    @property
    def check_type(self) -> str:
        return CheckType.CONSTRAINT_SATISFIED.value

    async def execute(
        self,
        subject_type: str,
        subject_id: str,
        inputs: dict[str, Any],
        policy: VerificationPolicy,
    ):
        constraints = inputs.get("constraints", [])
        actual_values = inputs.get("actual_values", {})

        if not constraints:
            return self._inconclusive(
                summary="No constraints provided for verification.",
                details={"reason": "no_constraints"},
            )

        violations: list[str] = []
        satisfied: list[str] = []

        for i, constraint in enumerate(constraints):
            c_type = constraint.get("type", "custom")
            field = constraint.get("field", "")
            operator = constraint.get("operator", "==")
            expected = constraint.get("expected")

            actual = actual_values.get(field)

            if actual is None and field:
                violations.append(
                    f"Constraint {i} ({c_type}): field '{field}' not found "
                    f"in actual values."
                )
                continue

            is_satisfied = self._evaluate(actual, operator, expected)

            if is_satisfied:
                satisfied.append(f"{field} {operator} {expected}")
            else:
                violations.append(
                    f"Constraint {i} ({c_type}): {field}={actual} "
                    f"does not satisfy {operator} {expected}."
                )

        if violations:
            return self._failed(
                summary=(
                    f"{len(violations)}/{len(constraints)} constraints violated."
                ),
                details={
                    "violations": violations,
                    "satisfied": satisfied,
                    "total": len(constraints),
                },
            )

        return self._passed(
            summary=f"All {len(constraints)} constraints satisfied.",
            details={"satisfied": satisfied, "total": len(constraints)},
        )

    @staticmethod
    def _evaluate(actual: Any, operator: str, expected: Any) -> bool:
        """Evaluate a single constraint expression."""
        try:
            if operator == "==":
                return actual == expected
            elif operator == "!=":
                return actual != expected
            elif operator == ">":
                return float(actual) > float(expected)
            elif operator == "<":
                return float(actual) < float(expected)
            elif operator == ">=":
                return float(actual) >= float(expected)
            elif operator == "<=":
                return float(actual) <= float(expected)
            elif operator == "in":
                return actual in expected
            elif operator == "contains":
                return expected in actual
            elif operator == "exists":
                return actual is not None
            elif operator == "not_exists":
                return actual is None
            else:
                return False
        except (TypeError, ValueError):
            return False