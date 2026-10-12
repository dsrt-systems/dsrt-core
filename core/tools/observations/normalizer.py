"""
Tool Output Normalizer & Security Filter (C3 §19, §41, §53).

Normalizes raw tool output into structured observations, redacts secrets,
and enforces output size limits.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from schemas.domain.enums import ObservationType
from schemas.domain.tool import ToolExecutionResult, ToolObservation

from core.kernel.fingerprint import content_hash
from core.observability.logging import get_logger
from core.storage.identifiers import IdPrefix, new_id


logger = get_logger("dsrt.tools.observations")

# Patterns that look like secrets (API keys, tokens, passwords)
_SECRET_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password|credential)\s*[:=]\s*['\"]?[\w\-]{16,}['\"]?"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),                    # OpenAI keys
    re.compile(r"AIza[a-zA-Z0-9\-_]{35}"),                  # Google API keys
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),                     # GitHub tokens
    re.compile(r"xox[bpsar]-[a-zA-Z0-9\-]{10,}"),           # Slack tokens
    re.compile(r"AKIA[A-Z0-9]{16}"),                        # AWS access keys
]

_REDACTED = "***REDACTED***"
_MAX_OBSERVATION_CONTENT_BYTES = 5 * 1024 * 1024  # 5 MB per observation


def redact_secrets(text: str) -> str:
    """Redact patterns that look like secrets from text."""
    result = text
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(_REDACTED, result)
    return result


def redact_secrets_in_dict(data: Any) -> Any:
    """Recursively redact secrets in a nested dict/list structure."""
    if isinstance(data, str):
        return redact_secrets(data)
    elif isinstance(data, dict):
        return {k: redact_secrets_in_dict(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [redact_secrets_in_dict(item) for item in data]
    return data


def normalize_output(
    raw_output: Any,
    *,
    tool_slug: str,
    tool_execution_id: str,
    execution_id: str,
    max_bytes: int = _MAX_OBSERVATION_CONTENT_BYTES,
) -> list[ToolObservation]:
    """Normalize raw tool output into a list of structured ToolObservations.

    Handles:
    - String outputs → TEXT observation
    - Dict outputs → STRUCTURED_DATA observation
    - List outputs → STRUCTURED_DATA observation
    - None → empty list
    - Size enforcement with truncation
    - Secret redaction
    """
    if raw_output is None:
        return []

    observations: list[ToolObservation] = []
    now = datetime.now(timezone.utc)

    # Convert to serializable form
    if isinstance(raw_output, str):
        content = raw_output
        obs_type = ObservationType.TEXT
    elif isinstance(raw_output, (dict, list)):
        content = raw_output
        obs_type = ObservationType.STRUCTURED_DATA
    else:
        content = str(raw_output)
        obs_type = ObservationType.TEXT

    # Redact secrets
    content = redact_secrets_in_dict(content)

    # Calculate size
    try:
        serialized = json.dumps(content, default=str)
        size_bytes = len(serialized.encode("utf-8"))
    except (TypeError, ValueError):
        serialized = str(content)
        size_bytes = len(serialized.encode("utf-8"))

    # Truncate if too large
    truncated = False
    if size_bytes > max_bytes:
        truncated = True
        if isinstance(content, str):
            content = content[: max_bytes // 2] + "\n... [TRUNCATED]"
        elif isinstance(content, dict):
            content = {"_truncated": True, "_original_size": size_bytes, "preview": str(content)[:1000]}
        elif isinstance(content, list):
            content = content[:10] + [{"_truncated": True, "_original_size": size_bytes}]
        size_bytes = max_bytes

    # Build summary
    summary = None
    if isinstance(content, str) and len(content) > 200:
        summary = content[:200] + "..."
    elif isinstance(content, dict):
        summary = f"Structured data with {len(content)} keys"
    elif isinstance(content, list):
        summary = f"List with {len(content)} items"

    obs = ToolObservation(
        observation_id=new_id(IdPrefix.TOOL_OBSERVATION),
        observation_type=obs_type,
        content=content,
        summary=summary,
        source=tool_slug,
        timestamp=now,
        truncated=truncated,
        size_bytes=size_bytes,
        provenance={
            "tool_execution_id": tool_execution_id,
            "execution_id": execution_id,
        },
    )
    observations.append(obs)

    return observations