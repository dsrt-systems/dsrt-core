"""
ModelFingerprint — Canonical model identity.

A model is NOT identified by display name alone. A fingerprint captures
the full identity so that evidence, profiles, and comparisons are
attributable to the exact model that actually executed.

Fingerprint fields (spec §6.B):
    provider
    model_id
    model_snapshot_or_version
    endpoint_identity
    inference_configuration
    quantization
    serving_hardware
    tool_capabilities

Unknown fields must be recorded as None/absent — never invented.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Fingerprint field enum (for documentation / introspection)
# ---------------------------------------------------------------------------

class FingerprintField(str, Enum):
    PROVIDER = "provider"
    MODEL_ID = "model_id"
    MODEL_SNAPSHOT = "model_snapshot"
    ENDPOINT_IDENTITY = "endpoint_identity"
    INFERENCE_CONFIGURATION = "inference_configuration"
    QUANTIZATION = "quantization"
    SERVING_HARDWARE = "serving_hardware"
    TOOL_CAPABILITIES = "tool_capabilities"


# ---------------------------------------------------------------------------
# Fingerprint schema
# ---------------------------------------------------------------------------

class ModelFingerprint(BaseModel):
    """
    Canonical identity of a specific model instance.

    Two executions sharing the same fingerprint_hash are guaranteed to
    have targeted the same model identity under the same inference
    configuration.
    """

    fingerprint_id: str = Field(default_factory=lambda: str(uuid4()))

    # Required identity
    provider: str
    model_id: str

    # Optional identity — record as None when unknown
    model_snapshot: str | None = None
    endpoint_identity: str | None = None
    quantization: str | None = None
    serving_hardware: str | None = None

    # Structured capability data
    inference_configuration: dict[str, Any] = Field(default_factory=dict)
    tool_capabilities: list[str] = Field(default_factory=list)

    # Integrity / provenance
    fingerprint_hash: str = ""
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # Fields known to be unavailable (recorded explicitly so profiles
    # don't later invent values).
    unknown_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _compute_hash_if_absent(self) -> ModelFingerprint:
        if not self.fingerprint_hash:
            self.fingerprint_hash = self.compute_hash()
        return self

    def compute_hash(self) -> str:
        """
        Deterministic SHA-256 hash of all identity fields.

        Hash is stable across equivalent fingerprints regardless of
        ``fingerprint_id`` or ``created_at``.
        """
        payload = {
            "provider": self.provider,
            "model_id": self.model_id,
            "model_snapshot": self.model_snapshot,
            "endpoint_identity": self.endpoint_identity,
            "quantization": self.quantization,
            "serving_hardware": self.serving_hardware,
            "inference_configuration": self.inference_configuration,
            "tool_capabilities": sorted(self.tool_capabilities),
        }
        canonical = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def matches(self, other: ModelFingerprint) -> bool:
        """Two fingerprints match if their identity hashes are equal."""
        return self.compute_hash() == other.compute_hash()

    def display_name(self) -> str:
        """Human-readable identifier combining provider, model, snapshot."""
        parts = [self.provider, self.model_id]
        if self.model_snapshot:
            parts.append(self.model_snapshot)
        return "/".join(parts)


# ---------------------------------------------------------------------------
# Fingerprinter
# ---------------------------------------------------------------------------

class ModelFingerprinter:
    """
    Builds a ``ModelFingerprint`` from raw model metadata.

    Accepts partial metadata and explicitly records fields it cannot
    determine rather than fabricating defaults.
    """

    REQUIRED_FIELDS = ("provider", "model_id")
    OPTIONAL_FIELDS = (
        "model_snapshot",
        "endpoint_identity",
        "quantization",
        "serving_hardware",
    )

    def fingerprint(
        self,
        *,
        provider: str,
        model_id: str,
        model_snapshot: str | None = None,
        endpoint_identity: str | None = None,
        inference_configuration: dict[str, Any] | None = None,
        quantization: str | None = None,
        serving_hardware: str | None = None,
        tool_capabilities: list[str] | None = None,
    ) -> ModelFingerprint:
        if not provider:
            raise ValueError("Fingerprint requires 'provider'.")
        if not model_id:
            raise ValueError("Fingerprint requires 'model_id'.")

        unknown: list[str] = []
        if model_snapshot is None:
            unknown.append(FingerprintField.MODEL_SNAPSHOT.value)
        if endpoint_identity is None:
            unknown.append(FingerprintField.ENDPOINT_IDENTITY.value)
        if quantization is None:
            unknown.append(FingerprintField.QUANTIZATION.value)
        if serving_hardware is None:
            unknown.append(FingerprintField.SERVING_HARDWARE.value)

        fp = ModelFingerprint(
            provider=provider,
            model_id=model_id,
            model_snapshot=model_snapshot,
            endpoint_identity=endpoint_identity,
            inference_configuration=self._normalize_inference_config(
                inference_configuration or {}
            ),
            quantization=quantization,
            serving_hardware=serving_hardware,
            tool_capabilities=sorted(tool_capabilities or []),
            unknown_fields=unknown,
        )
        return fp

    def from_provider_response(
        self,
        *,
        provider: str,
        model_id: str,
        provider_metadata: dict[str, Any],
    ) -> ModelFingerprint:
        """
        Extract a fingerprint from a provider's model-info response.

        Only fields the provider actually returned are populated.
        """
        return self.fingerprint(
            provider=provider,
            model_id=model_id,
            model_snapshot=provider_metadata.get("snapshot")
            or provider_metadata.get("version")
            or provider_metadata.get("model_version"),
            endpoint_identity=provider_metadata.get("endpoint"),
            inference_configuration=provider_metadata.get(
                "inference_configuration", {}
            ),
            quantization=provider_metadata.get("quantization"),
            serving_hardware=provider_metadata.get("serving_hardware"),
            tool_capabilities=provider_metadata.get("tool_capabilities", []),
        )

    @staticmethod
    def _normalize_inference_config(cfg: dict[str, Any]) -> dict[str, Any]:
        """
        Normalize inference config so semantically equivalent configs
        produce identical fingerprint hashes.
        """
        # Drop keys with None values; preserve numeric precision
        return {k: v for k, v in cfg.items() if v is not None}