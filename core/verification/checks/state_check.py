"""
State Consistency Check (C6 §25).

Validates shared state consistency across nodes.
Deterministic — checks for conflicting values and schema violations.

Expected inputs:
  - inputs["state"]: dict of the shared state
  - inputs["expected_fields"]: list of required field paths
  - inputs["node_outputs"]: dict mapping node_key -> output dict
"""

from __future__ import annotations

from typing import Any

from schemas.domain.enums import CheckType
from schemas.domain.verification import VerificationPolicy

from core.verification.checks.base import BaseCheck


class StateCheck(BaseCheck):
    """Validates shared state consistency (C6 §25)."""

    @property
    def check_type(self) -> str:
        return CheckType.STATE_CONSISTENT.value

    async def execute(
        self,
        subject_type: str,
        subject_id: str,
        inputs: dict[str, Any],
        policy: VerificationPolicy,
    ):
        state = inputs.get("state", {})
        expected_fields = inputs.get("expected_fields", [])
        node_outputs = inputs.get("node_outputs", {})

        errors: list[str] = []
        warnings: list[str] = []

        # 1. Required fields check
        for field_path in expected_fields:
            value = self._get_nested(state, field_path)
            if value is None:
                errors.append(f"Required state field missing: '{field_path}'.")

        # 2. Cross-node consistency check
        if node_outputs and len(node_outputs) > 1:
            # Check for conflicting values across nodes
            field_values: dict[str, dict[str, Any]] = {}

            for node_key, output in node_outputs.items():
                if not isinstance(output, dict):
                    continue
                for key, value in output.items():
                    if key not in field_values:
                        field_values[key] = {}
                    field_values[key][node_key] = value

            for field, node_vals in field_values.items():
                if len(node_vals) > 1:
                    unique_vals = set()
                    for v in node_vals.values():
                        try:
                            unique_vals.add(str(v))
                        except TypeError:
                            unique_vals.add(repr(v))

                    if len(unique_vals) > 1:
                        conflicts = {
                            k: v for k, v in node_vals.items()
                        }
                        warnings.append(
                            f"Cross-node conflict on '{field}': {conflicts}"
                        )

        # 3. State type consistency
        for key, value in state.items():
            if isinstance(value, dict) and not value:
                warnings.append(f"State field '{key}' is an empty dict.")

        if errors:
            return self._failed(
                summary=f"State consistency failed: {len(errors)} error(s).",
                details={
                    "errors": errors,
                    "warnings": warnings,
                    "fields_checked": len(expected_fields),
                    "nodes_checked": len(node_outputs),
                },
            )

        if warnings:
            return self._warning(
                summary=f"State consistent with {len(warnings)} warning(s).",
                details={"warnings": warnings},
            )

        return self._passed(
            summary="State consistency verified.",
            details={
                "fields_checked": len(expected_fields),
                "nodes_checked": len(node_outputs),
            },
        )

    @staticmethod
    def _get_nested(data: dict, path: str) -> Any:
        """Navigate a nested dict using dot-notation path."""
        keys = path.split(".")
        current = data
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None
        return current