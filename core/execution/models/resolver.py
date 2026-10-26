"""
ModelResolver — Resolves a model selection into an actual usable connection.

Resolution is distinct from invocation:
    - ModelResolver answers "can I use this model, and what exactly is it?"
    - C2 ModelGateway answers "send this request to that model."

A resolver query produces:
    - A validated connection
    - A canonical ModelFingerprint
    - A capability snapshot (what the connection actually supports)

The resolver does NOT store credentials. Credentials remain in C2's
secure credential vault. The resolver only references them by
connection_id.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from core.execution.models.fingerprint import (
    ModelFingerprint,
    ModelFingerprinter,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ResolutionError(Exception):
    """Base class for resolver failures."""


class ConnectionNotFoundError(ResolutionError):
    """Requested connection does not exist for this workspace/user."""


class ConnectionUnavailableError(ResolutionError):
    """Connection exists but is not reachable or has been revoked."""


class CapabilityMismatchError(ResolutionError):
    """Model does not support a required capability."""


# ---------------------------------------------------------------------------
# Connection source
# ---------------------------------------------------------------------------

class ConnectionSource(str, Enum):
    """Where the connection credentials/access come from."""

    USER_BYOK = "USER_BYOK"              # User-provided API key
    DSRT_MANAGED = "DSRT_MANAGED"        # DSRT-managed provider access
    DSRT_HOSTED = "DSRT_HOSTED"          # DSRT-hosted open-weight model
    OPENAI_COMPATIBLE = "OPENAI_COMPATIBLE"  # OpenAI-compatible endpoint


# ---------------------------------------------------------------------------
# Gateway adapter contract
# ---------------------------------------------------------------------------

class ModelGatewayAdapter(Protocol):
    """
    Minimal contract the resolver uses to interact with C2 Model Gateway.

    An adapter implementation wraps the real C2 gateway and exposes
    only the resolution-safe operations (no credential leakage).
    """

    async def get_connection(
        self,
        *,
        workspace_id: str,
        connection_id: str,
    ) -> dict[str, Any] | None:
        """Return connection metadata or None if not found."""
        ...

    async def verify_connection(
        self,
        *,
        workspace_id: str,
        connection_id: str,
    ) -> dict[str, Any]:
        """
        Perform a lightweight reachability check.
        Returns {"reachable": bool, "latency_ms": int, "error": str | None}.
        """
        ...

    async def get_model_metadata(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        model_id: str,
    ) -> dict[str, Any]:
        """Return provider-reported model metadata."""
        ...


# ---------------------------------------------------------------------------
# Resolved connection schema
# ---------------------------------------------------------------------------

class ResolvedModelConnection(BaseModel):
    """
    Result of a successful model resolution.

    Never contains credentials. Contains only identity, capabilities,
    and the connection_id that C2 can use to retrieve credentials from
    its vault at invocation time.
    """

    resolution_id: str = Field(default_factory=lambda: str(uuid4()))
    workspace_id: str
    connection_id: str
    connection_source: ConnectionSource

    # Model identity
    fingerprint: ModelFingerprint

    # Resolved endpoint information (identity only — no secrets)
    endpoint_identity: str | None = None
    provider_display_name: str = ""

    # Verified capabilities at resolution time
    capabilities: list[str] = Field(default_factory=list)
    supports_streaming: bool = False
    supports_tool_use: bool = False
    supports_vision: bool = False
    context_window_tokens: int | None = None
    max_output_tokens: int | None = None

    # Rate limits (if known)
    rate_limit_rpm: int | None = None
    rate_limit_tpm: int | None = None

    # Resolution metadata
    reachable: bool = False
    reachability_latency_ms: int | None = None
    resolved_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

class ModelResolver:
    """
    Resolves a model selection into a verified ResolvedModelConnection.

    Credentials never leave the C2 vault. This resolver only sees
    connection metadata, model metadata, and reachability status.
    """

    def __init__(
        self,
        *,
        gateway: ModelGatewayAdapter,
        fingerprinter: ModelFingerprinter | None = None,
    ) -> None:
        self._gateway = gateway
        self._fingerprinter = fingerprinter or ModelFingerprinter()

    async def resolve(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        model_id: str,
        required_capabilities: list[str] | None = None,
        verify_reachable: bool = True,
    ) -> ResolvedModelConnection:
        """
        Resolve a model selection end-to-end.

        Steps:
        1. Fetch connection metadata (fail if missing).
        2. Optionally verify reachability.
        3. Fetch model metadata from provider.
        4. Build fingerprint.
        5. Validate required capabilities.
        6. Return ResolvedModelConnection.
        """
        required = required_capabilities or []
        warnings: list[str] = []

        # 1. Connection lookup
        connection = await self._gateway.get_connection(
            workspace_id=workspace_id,
            connection_id=connection_id,
        )
        if connection is None:
            raise ConnectionNotFoundError(
                f"Connection '{connection_id}' not found for workspace "
                f"'{workspace_id}'."
            )

        source_raw = connection.get("source") or ConnectionSource.USER_BYOK.value
        try:
            source = ConnectionSource(source_raw)
        except ValueError:
            source = ConnectionSource.USER_BYOK
            warnings.append(
                f"Unknown connection source '{source_raw}'; "
                f"defaulting to USER_BYOK."
            )

        # 2. Reachability check
        reachable = True
        latency_ms: int | None = None
        if verify_reachable:
            check = await self._gateway.verify_connection(
                workspace_id=workspace_id,
                connection_id=connection_id,
            )
            reachable = bool(check.get("reachable", False))
            latency_ms = check.get("latency_ms")
            if not reachable:
                err = check.get("error") or "connection unreachable"
                raise ConnectionUnavailableError(
                    f"Connection '{connection_id}' is not reachable: {err}"
                )

        # 3. Model metadata
        try:
            metadata = await self._gateway.get_model_metadata(
                workspace_id=workspace_id,
                connection_id=connection_id,
                model_id=model_id,
            )
        except Exception as exc:
            logger.warning(
                "Failed to fetch model metadata for %s/%s: %s",
                connection_id, model_id, exc,
            )
            metadata = {}
            warnings.append(f"Model metadata unavailable: {exc}")

        provider = connection.get("provider") or metadata.get("provider") or ""
        if not provider:
            raise ResolutionError(
                f"Cannot resolve model '{model_id}': provider not identified."
            )

        # 4. Fingerprint
        fingerprint = self._fingerprinter.from_provider_response(
            provider=provider,
            model_id=model_id,
            provider_metadata=metadata,
        )

        # 5. Capability validation
        capabilities = list(metadata.get("capabilities", []))
        missing = [cap for cap in required if cap not in capabilities]
        if missing:
            raise CapabilityMismatchError(
                f"Model '{model_id}' is missing required capabilities: "
                f"{missing}. Supported: {capabilities}"
            )

        # 6. Build result
        return ResolvedModelConnection(
            workspace_id=workspace_id,
            connection_id=connection_id,
            connection_source=source,
            fingerprint=fingerprint,
            endpoint_identity=metadata.get("endpoint")
            or connection.get("endpoint"),
            provider_display_name=connection.get(
                "display_name", provider
            ),
            capabilities=capabilities,
            supports_streaming=bool(metadata.get("supports_streaming", False)),
            supports_tool_use=bool(metadata.get("supports_tool_use", False)),
            supports_vision=bool(metadata.get("supports_vision", False)),
            context_window_tokens=metadata.get("context_window_tokens"),
            max_output_tokens=metadata.get("max_output_tokens"),
            rate_limit_rpm=connection.get("rate_limit_rpm"),
            rate_limit_tpm=connection.get("rate_limit_tpm"),
            reachable=reachable,
            reachability_latency_ms=latency_ms,
            warnings=warnings,
        )