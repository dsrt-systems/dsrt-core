"""
Artifact Integrity Check (C6 §23-24).

Validates artifact structure, parseability, and integrity.
Deterministic — checks format, size, checksum, and structure.

Expected inputs:
  - inputs["artifact"]: dict with keys: content, mime_type, size_bytes, checksum
  - inputs["expected_mime_type"]: optional expected MIME type
  - inputs["max_size_bytes"]: optional max size
"""

from __future__ import annotations

import hashlib
from typing import Any

from schemas.domain.enums import CheckType
from schemas.domain.verification import VerificationPolicy

from core.verification.checks.base import BaseCheck


class ArtifactCheck(BaseCheck):
    """Validates artifact integrity and structure (C6 §23-24)."""

    @property
    def check_type(self) -> str:
        return CheckType.ARTIFACT_INTEGRITY.value

    async def execute(
        self,
        subject_type: str,
        subject_id: str,
        inputs: dict[str, Any],
        policy: VerificationPolicy,
    ):
        artifact = inputs.get("artifact")

        if artifact is None:
            return self._failed(
                summary="No artifact provided for integrity check.",
                details={"reason": "missing_artifact"},
            )

        errors: list[str] = []
        warnings: list[str] = []
        checks_performed: list[str] = []

        content = artifact.get("content", "")
        mime_type = artifact.get("mime_type", "")
        size_bytes = artifact.get("size_bytes")
        checksum = artifact.get("checksum")

        # 1. Existence check
        if not content and size_bytes != 0:
            errors.append("Artifact has no content.")
        else:
            checks_performed.append("existence")

        # 2. Size check
        if size_bytes is not None:
            max_size = inputs.get("max_size_bytes")
            if max_size and size_bytes > max_size:
                errors.append(
                    f"Artifact size {size_bytes} exceeds maximum {max_size}."
                )
            if size_bytes < 0:
                errors.append("Artifact size cannot be negative.")
            checks_performed.append("size")

        # 3. MIME type check
        expected_mime = inputs.get("expected_mime_type")
        if expected_mime and mime_type != expected_mime:
            warnings.append(
                f"MIME type mismatch: expected '{expected_mime}', "
                f"got '{mime_type}'."
            )
        if not mime_type:
            warnings.append("No MIME type specified.")
        checks_performed.append("mime_type")

        # 4. Checksum integrity
        if checksum and content:
            computed = hashlib.sha256(
                content.encode("utf-8") if isinstance(content, str) else content
            ).hexdigest()
            if computed != checksum:
                errors.append(
                    f"Checksum mismatch: expected {checksum[:16]}..., "
                    f"computed {computed[:16]}..."
                )
            else:
                checks_performed.append("checksum")

        # 5. Parseability check based on MIME type
        if content and mime_type:
            if "json" in mime_type:
                try:
                    import json
                    json.loads(content) if isinstance(content, str) else content
                    checks_performed.append("json_parseable")
                except (json.JSONDecodeError, TypeError):
                    errors.append("Artifact claims JSON but is not parseable.")

            elif "markdown" in mime_type or "text" in mime_type:
                if isinstance(content, str) and len(content.strip()) > 0:
                    checks_performed.append("text_parseable")
                else:
                    errors.append("Text artifact is empty or not a string.")

        if errors:
            return self._failed(
                summary=f"Artifact integrity failed: {len(errors)} error(s).",
                details={
                    "errors": errors,
                    "warnings": warnings,
                    "checks_performed": checks_performed,
                },
            )

        if warnings:
            return self._warning(
                summary=f"Artifact valid with {len(warnings)} warning(s).",
                details={
                    "warnings": warnings,
                    "checks_performed": checks_performed,
                },
            )

        return self._passed(
            summary="Artifact integrity verified.",
            details={"checks_performed": checks_performed},
        )