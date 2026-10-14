"""
Schema Validation Check (C6 §11, §23).

Validates that the output conforms to an expected JSON schema.
Deterministic — uses structural validation only.

Expected inputs:
  - inputs["output"]: The output to validate (dict)
  - inputs["expected_schema"]: JSON schema dict with "required" fields
"""

from __future__ import annotations

from typing import Any

from schemas.domain.enums import CheckType
from schemas.domain.verification import VerificationPolicy

from core.verification.checks.base import BaseCheck


class SchemaCheck(BaseCheck):
    """Validates output against a JSON schema (C6 §23)."""

    @property
    def check_type(self) -> str:
        return CheckType.SCHEMA_VALID.value

    async def execute(
        self,
        subject_type: str,
        subject_id: str,
        inputs: dict[str, Any],
        policy: VerificationPolicy,
    ):
        output = inputs.get("output")
        expected_schema = inputs.get("expected_schema")

        if output is None:
            return self._failed(
                summary="No output provided for schema validation.",
                details={"reason": "missing_output"},
            )

        if expected_schema is None:
            return self._inconclusive(
                summary="No expected schema provided. Cannot validate.",
                details={"reason": "missing_schema"},
            )

        errors: list[str] = []
        warnings: list[str] = []

        # 1. Type check
        expected_type = expected_schema.get("type")
        if expected_type == "object" and not isinstance(output, dict):
            errors.append(f"Expected object, got {type(output).__name__}.")
        elif expected_type == "array" and not isinstance(output, list):
            errors.append(f"Expected array, got {type(output).__name__}.")
        elif expected_type == "string" and not isinstance(output, str):
            errors.append(f"Expected string, got {type(output).__name__}.")

        # 2. Required fields check
        if isinstance(output, dict):
            required_fields = expected_schema.get("required", [])
            for field in required_fields:
                if field not in output:
                    errors.append(f"Missing required field: '{field}'.")

            # 3. Nested property type checks
            properties = expected_schema.get("properties", {})
            for prop_name, prop_schema in properties.items():
                if prop_name in output:
                    prop_type = prop_schema.get("type")
                    value = output[prop_name]
                    if prop_type == "string" and not isinstance(value, str):
                        errors.append(
                            f"Field '{prop_name}' expected string, "
                            f"got {type(value).__name__}."
                        )
                    elif prop_type == "number" and not isinstance(value, (int, float)):
                        errors.append(
                            f"Field '{prop_name}' expected number, "
                            f"got {type(value).__name__}."
                        )
                    elif prop_type == "array" and not isinstance(value, list):
                        errors.append(
                            f"Field '{prop_name}' expected array, "
                            f"got {type(value).__name__}."
                        )
                    elif prop_type == "object" and not isinstance(value, dict):
                        errors.append(
                            f"Field '{prop_name}' expected object, "
                            f"got {type(value).__name__}."
                        )

            # 4. Additional properties warning
            if expected_schema.get("additionalProperties") is False:
                extra = set(output.keys()) - set(properties.keys())
                if extra:
                    warnings.append(
                        f"Unexpected fields: {sorted(extra)}"
                    )

        # 5. Min/max length for strings
        if isinstance(output, str):
            min_len = expected_schema.get("minLength")
            max_len = expected_schema.get("maxLength")
            if min_len and len(output) < min_len:
                errors.append(
                    f"String length {len(output)} below minimum {min_len}."
                )
            if max_len and len(output) > max_len:
                errors.append(
                    f"String length {len(output)} exceeds maximum {max_len}."
                )

        # 6. Min/max items for arrays
        if isinstance(output, list):
            min_items = expected_schema.get("minItems")
            max_items = expected_schema.get("maxItems")
            if min_items and len(output) < min_items:
                errors.append(
                    f"Array length {len(output)} below minimum {min_items}."
                )
            if max_items and len(output) > max_items:
                errors.append(
                    f"Array length {len(output)} exceeds maximum {max_items}."
                )

        if errors:
            return self._failed(
                summary=f"Schema validation failed: {len(errors)} error(s).",
                details={"errors": errors, "warnings": warnings},
            )

        if warnings:
            return self._warning(
                summary=f"Schema valid with {len(warnings)} warning(s).",
                details={"warnings": warnings},
            )

        return self._passed(
            summary="Output conforms to expected schema.",
            details={"fields_checked": len(expected_schema.get("properties", {}))},
        )