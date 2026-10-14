"""
Tool Result Validation Check (C6 §26).

Validates that tool execution results are usable and correct.
Deterministic — asserts only what the tool result declares.

Design note:
  This check does NOT apply arbitrary heuristics such as "short output is
  suspicious" or "the substring 'error' implies failure". Those produce
  false positives on legitimate results ("42", "OK", "error_rate: 0.0").
  Any length or shape expectation must be declared explicitly on the result.

Expected inputs:
  - inputs["tool_results"]: list of tool result dicts:
      - "tool_slug": str
      - "status": "SUCCESS" | "COMPLETED" | "FAILED" | "DENIED" | ...
      - "output": dict | list | str | number | bool | None
      - "error": str | None
      - "expected_schema": dict | None      # JSON-schema subset
      - "min_output_length": int | None     # opt-in, strings only
      - "allow_empty_output": bool          # default False -> warning
"""

from __future__ import annotations

from typing import Any

from schemas.domain.enums import CheckType
from schemas.domain.verification import VerificationPolicy

from core.verification.checks.base import BaseCheck


_FAILURE_STATUSES = frozenset({"FAILED", "DENIED", "CANCELLED", "TIMEOUT"})
_SUCCESS_STATUSES = frozenset({"SUCCESS", "COMPLETED"})

_JSON_TYPE_MAP: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
}


class ToolCheck(BaseCheck):
    """Validates tool execution results (C6 §26)."""

    @property
    def check_type(self) -> str:
        return CheckType.TOOL_RESULT_VALID.value

    async def execute(
        self,
        subject_type: str,
        subject_id: str,
        inputs: dict[str, Any],
        policy: VerificationPolicy,
    ):
        tool_results = inputs.get("tool_results")

        if tool_results is None:
            return self._inconclusive(
                summary="No tool results provided for validation.",
                details={"reason": "no_tool_results"},
            )

        if not isinstance(tool_results, list):
            return self._failed(
                summary="tool_results must be a list.",
                details={
                    "reason": "invalid_input_type",
                    "actual_type": type(tool_results).__name__,
                },
            )

        if not tool_results:
            return self._inconclusive(
                summary="Empty tool result list provided.",
                details={"reason": "no_tool_results"},
            )

        errors: list[str] = []
        warnings: list[str] = []
        valid_count = 0

        for index, result in enumerate(tool_results):
            if not isinstance(result, dict):
                errors.append(
                    f"Tool result {index} is not an object "
                    f"(got {type(result).__name__})."
                )
                continue

            tool_slug = result.get("tool_slug") or f"tool_{index}"
            status = result.get("status", "UNKNOWN")
            output = result.get("output")
            error = result.get("error")

            result_errors: list[str] = []
            result_warnings: list[str] = []

            # 1. Declared failure status is a hard error.
            if status in _FAILURE_STATUSES:
                errors.append(
                    f"Tool '{tool_slug}' reported status {status}: "
                    f"{error or 'no error detail provided'}."
                )
                continue

            # 2. Unrecognized status is a warning, not a failure.
            if status not in _SUCCESS_STATUSES:
                result_warnings.append(
                    f"Tool '{tool_slug}' reported unrecognized status '{status}'."
                )

            # 3. Error field populated despite a non-failure status.
            if error:
                result_warnings.append(
                    f"Tool '{tool_slug}' reported status '{status}' but also "
                    f"carries an error field."
                )

            # 4. Output presence.
            if self._is_empty_output(output):
                if not bool(result.get("allow_empty_output", False)):
                    result_warnings.append(
                        f"Tool '{tool_slug}' returned empty output."
                    )
            else:
                # 5. Declared schema.
                result_errors.extend(
                    self._validate_against_schema(
                        tool_slug, output, result.get("expected_schema"),
                    )
                )

                # 6. Opt-in minimum length (strings only).
                min_len = result.get("min_output_length")
                if isinstance(min_len, int) and isinstance(output, str):
                    if len(output) < min_len:
                        result_errors.append(
                            f"Tool '{tool_slug}' output length {len(output)} "
                            f"is below the declared minimum {min_len}."
                        )

            errors.extend(result_errors)
            warnings.extend(result_warnings)

            if not result_errors:
                valid_count += 1

        total = len(tool_results)

        if errors:
            return self._failed(
                summary=(
                    f"Tool validation failed: {len(errors)} error(s) "
                    f"across {total} tool result(s)."
                ),
                details={
                    "errors": errors,
                    "warnings": warnings,
                    "valid": valid_count,
                    "total": total,
                },
            )

        if warnings:
            return self._warning(
                summary=f"Tool results valid with {len(warnings)} warning(s).",
                details={
                    "warnings": warnings,
                    "valid": valid_count,
                    "total": total,
                },
            )

        return self._passed(
            summary=f"All {total} tool results validated.",
            details={"valid": valid_count, "total": total},
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_empty_output(output: Any) -> bool:
        """Empty means absent or zero-length — not merely falsy.

        0, 0.0, and False are legitimate tool outputs.
        """
        if output is None:
            return True
        if isinstance(output, str):
            return not output.strip()
        if isinstance(output, (list, dict, tuple, set)):
            return len(output) == 0
        return False

    @classmethod
    def _matches_json_type(cls, value: Any, json_type: str) -> bool:
        """Type check with correct bool/int separation."""
        if json_type == "null":
            return value is None
        if json_type == "boolean":
            return isinstance(value, bool)
        if json_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if json_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)

        expected = _JSON_TYPE_MAP.get(json_type)
        if expected is None:
            # Unknown type declaration — do not fail on it.
            return True
        return isinstance(value, expected)

    @classmethod
    def _validate_against_schema(
        cls,
        tool_slug: str,
        output: Any,
        schema: Any,
    ) -> list[str]:
        """Validate output against a declared JSON-schema subset."""
        if not isinstance(schema, dict) or not schema:
            return []

        errors: list[str] = []

        declared_type = schema.get("type")
        if isinstance(declared_type, str):
            if not cls._matches_json_type(output, declared_type):
                errors.append(
                    f"Tool '{tool_slug}' output expected type "
                    f"'{declared_type}', got '{type(output).__name__}'."
                )
                # Field-level checks are meaningless once the type is wrong.
                return errors

        if isinstance(output, dict):
            for field in schema.get("required") or []:
                if field not in output:
                    errors.append(
                        f"Tool '{tool_slug}' output missing required "
                        f"field '{field}'."
                    )

            for prop, prop_schema in (schema.get("properties") or {}).items():
                if prop not in output or not isinstance(prop_schema, dict):
                    continue
                prop_type = prop_schema.get("type")
                if isinstance(prop_type, str):
                    if not cls._matches_json_type(output[prop], prop_type):
                        errors.append(
                            f"Tool '{tool_slug}' field '{prop}' expected type "
                            f"'{prop_type}', got "
                            f"'{type(output[prop]).__name__}'."
                        )

        elif schema.get("required") or schema.get("properties"):
            # Schema describes an object but the tool returned something else.
            errors.append(
                f"Tool '{tool_slug}' declares an object schema but returned "
                f"'{type(output).__name__}'."
            )

        return errors