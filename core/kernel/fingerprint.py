"""
Configuration Fingerprint.

Deterministic hash of an execution's complete configuration. Enables
reproducibility (C1 §39) and future Arena reproducibility (C8).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def configuration_fingerprint(
    *,
    core_version: str,
    agent_version_id: str,
    contract_version: str,
    model_id: str | None,
    resource_limits: dict[str, Any],
    task_input_hash: str,
    extra: dict[str, Any] | None = None,
) -> str:
    """Compute the deterministic sha256 fingerprint of an execution's config.

    The fingerprint is JSON-serialization-independent: keys are sorted.
    """
    payload: dict[str, Any] = {
        "core_version": core_version,
        "agent_version_id": agent_version_id,
        "contract_version": contract_version,
        "model_id": model_id,
        "resource_limits": resource_limits,
        "task_input_hash": task_input_hash,
    }
    if extra:
        payload["extra"] = extra

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def content_hash(content: bytes | str) -> str:
    """Compute sha256 of arbitrary content."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def payload_hash(payload: dict[str, Any]) -> str:
    """Deterministic hash of a JSON-serializable payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()