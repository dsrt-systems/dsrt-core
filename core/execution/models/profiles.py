"""
ProfileRegistry — Three-layer profile storage.

Layers (spec §6.C):
    SharedModelProfile    — Reusable model-level capability + benchmark evidence
    ConnectionProfile     — User-specific endpoint, access, permissions, limits
    ExecutionProfile      — Observed runtime behavior for a specific config

Rules:
    - Credentials NEVER live in profile records.
    - A reused shared profile MUST NEVER be presented as a fresh
      experiment on the user's own connection (enforced via
      ``is_reused_evidence`` flag on query results).
    - Profiles are keyed by fingerprint_hash so changes in model
      identity automatically produce new profiles.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from core.execution.models.fingerprint import ModelFingerprint

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Profile schemas
# ---------------------------------------------------------------------------

class SharedModelProfile(BaseModel):
    """
    Model-level knowledge that can be shared across users.

    Example: "gpt-4o scored X on benchmark Y as of date Z". No user
    credentials, no workspace-specific state.
    """

    profile_id: str = Field(default_factory=lambda: str(uuid4()))
    fingerprint_hash: str

    provider: str
    model_id: str
    model_snapshot: str | None = None

    # Capability flags
    capabilities: list[str] = Field(default_factory=list)
    context_window_tokens: int | None = None
    max_output_tokens: int | None = None

    # Benchmark evidence (references to C8 evaluation results)
    benchmark_evidence: list[dict[str, Any]] = Field(default_factory=list)

    # Observed performance aggregates
    avg_latency_ms: float | None = None
    avg_cost_per_1k_tokens_usd: float | None = None

    # Provenance
    evidence_count: int = 0
    source_count: int = 0  # Number of distinct connections contributing
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    schema_version: str = "1.0.0"


class ConnectionProfile(BaseModel):
    """
    Per-user/per-workspace connection record.

    Credentials live in C2's vault. This profile stores only
    identity, limits, and permissions.
    """

    profile_id: str = Field(default_factory=lambda: str(uuid4()))
    workspace_id: str
    connection_id: str

    provider: str
    display_name: str = ""
    endpoint_identity: str | None = None
    connection_source: str = ""  # ConnectionSource value

    rate_limit_rpm: int | None = None
    rate_limit_tpm: int | None = None
    allowed_models: list[str] = Field(default_factory=list)
    allowed_capabilities: list[str] = Field(default_factory=list)

    verified_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class ExecutionProfile(BaseModel):
    """
    Observed runtime behavior for a specific (fingerprint + connection)
    pair over time. Updated incrementally from execution evidence.
    """

    profile_id: str = Field(default_factory=lambda: str(uuid4()))
    workspace_id: str
    connection_id: str
    fingerprint_hash: str

    # Observed metrics
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    total_duration_ms: int = 0

    # Latency distribution
    min_latency_ms: int | None = None
    max_latency_ms: int | None = None
    avg_latency_ms: float | None = None

    # Reliability
    error_counts: dict[str, int] = Field(default_factory=dict)

    first_execution_at: datetime | None = None
    last_execution_at: datetime | None = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def success_rate(self) -> float | None:
        if self.total_executions == 0:
            return None
        return self.successful_executions / self.total_executions


# ---------------------------------------------------------------------------
# Storage contract
# ---------------------------------------------------------------------------

class ProfileStore(Protocol):
    """Pluggable persistence backend. In production this wraps the C10 repos."""

    async def get_shared(self, fingerprint_hash: str) -> SharedModelProfile | None: ...
    async def upsert_shared(self, profile: SharedModelProfile) -> SharedModelProfile: ...

    async def get_connection(
        self, *, workspace_id: str, connection_id: str,
    ) -> ConnectionProfile | None: ...
    async def upsert_connection(
        self, profile: ConnectionProfile,
    ) -> ConnectionProfile: ...

    async def get_execution(
        self, *, workspace_id: str, connection_id: str, fingerprint_hash: str,
    ) -> ExecutionProfile | None: ...
    async def upsert_execution(
        self, profile: ExecutionProfile,
    ) -> ExecutionProfile: ...


# ---------------------------------------------------------------------------
# In-memory default store (production uses C10 repositories)
# ---------------------------------------------------------------------------

class InMemoryProfileStore:
    """Default store for tests and development."""

    def __init__(self) -> None:
        self._shared: dict[str, SharedModelProfile] = {}
        self._connection: dict[tuple[str, str], ConnectionProfile] = {}
        self._execution: dict[tuple[str, str, str], ExecutionProfile] = {}

    async def get_shared(self, fingerprint_hash: str) -> SharedModelProfile | None:
        return self._shared.get(fingerprint_hash)

    async def upsert_shared(self, profile: SharedModelProfile) -> SharedModelProfile:
        profile.updated_at = datetime.now(timezone.utc)
        self._shared[profile.fingerprint_hash] = profile
        return profile

    async def get_connection(
        self, *, workspace_id: str, connection_id: str,
    ) -> ConnectionProfile | None:
        return self._connection.get((workspace_id, connection_id))

    async def upsert_connection(
        self, profile: ConnectionProfile,
    ) -> ConnectionProfile:
        self._connection[(profile.workspace_id, profile.connection_id)] = profile
        return profile

    async def get_execution(
        self, *, workspace_id: str, connection_id: str, fingerprint_hash: str,
    ) -> ExecutionProfile | None:
        return self._execution.get(
            (workspace_id, connection_id, fingerprint_hash)
        )

    async def upsert_execution(
        self, profile: ExecutionProfile,
    ) -> ExecutionProfile:
        self._execution[
            (profile.workspace_id, profile.connection_id, profile.fingerprint_hash)
        ] = profile
        return profile


# ---------------------------------------------------------------------------
# Service classes
# ---------------------------------------------------------------------------

class SharedProfileService:
    """Operations on SharedModelProfile."""

    def __init__(self, store: ProfileStore) -> None:
        self._store = store

    async def get_or_create(
        self, fingerprint: ModelFingerprint,
    ) -> tuple[SharedModelProfile, bool]:
        """Return (profile, created_flag)."""
        existing = await self._store.get_shared(fingerprint.fingerprint_hash)
        if existing is not None:
            return existing, False

        profile = SharedModelProfile(
            fingerprint_hash=fingerprint.fingerprint_hash,
            provider=fingerprint.provider,
            model_id=fingerprint.model_id,
            model_snapshot=fingerprint.model_snapshot,
            capabilities=list(fingerprint.tool_capabilities),
        )
        stored = await self._store.upsert_shared(profile)
        return stored, True

    async def record_benchmark_evidence(
        self,
        *,
        fingerprint_hash: str,
        evidence: dict[str, Any],
        source_connection_id: str,
    ) -> SharedModelProfile:
        profile = await self._store.get_shared(fingerprint_hash)
        if profile is None:
            raise ValueError(
                f"No shared profile for fingerprint '{fingerprint_hash}'."
            )
        tagged = {**evidence, "source_connection_id": source_connection_id}
        profile.benchmark_evidence.append(tagged)
        profile.evidence_count += 1
        existing_sources = {
            e.get("source_connection_id")
            for e in profile.benchmark_evidence
            if e.get("source_connection_id")
        }
        profile.source_count = len(existing_sources)
        return await self._store.upsert_shared(profile)


class ConnectionProfileService:
    """Operations on ConnectionProfile."""

    def __init__(self, store: ProfileStore) -> None:
        self._store = store

    async def register(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        provider: str,
        display_name: str = "",
        connection_source: str = "USER_BYOK",
        endpoint_identity: str | None = None,
        rate_limit_rpm: int | None = None,
        rate_limit_tpm: int | None = None,
        allowed_models: list[str] | None = None,
        allowed_capabilities: list[str] | None = None,
    ) -> ConnectionProfile:
        profile = ConnectionProfile(
            workspace_id=workspace_id,
            connection_id=connection_id,
            provider=provider,
            display_name=display_name,
            endpoint_identity=endpoint_identity,
            connection_source=connection_source,
            rate_limit_rpm=rate_limit_rpm,
            rate_limit_tpm=rate_limit_tpm,
            allowed_models=allowed_models or [],
            allowed_capabilities=allowed_capabilities or [],
            verified_at=datetime.now(timezone.utc),
        )
        return await self._store.upsert_connection(profile)

    async def get(
        self, *, workspace_id: str, connection_id: str,
    ) -> ConnectionProfile | None:
        return await self._store.get_connection(
            workspace_id=workspace_id,
            connection_id=connection_id,
        )

    async def revoke(
        self, *, workspace_id: str, connection_id: str,
    ) -> ConnectionProfile:
        profile = await self._store.get_connection(
            workspace_id=workspace_id,
            connection_id=connection_id,
        )
        if profile is None:
            raise ValueError(
                f"Connection '{connection_id}' not found for workspace "
                f"'{workspace_id}'."
            )
        profile.revoked_at = datetime.now(timezone.utc)
        return await self._store.upsert_connection(profile)


class ExecutionProfileService:
    """Operations on ExecutionProfile — observed runtime behavior."""

    def __init__(self, store: ProfileStore) -> None:
        self._store = store

    async def record_execution(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        fingerprint_hash: str,
        succeeded: bool,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        duration_ms: int,
        error_type: str | None = None,
    ) -> ExecutionProfile:
        existing = await self._store.get_execution(
            workspace_id=workspace_id,
            connection_id=connection_id,
            fingerprint_hash=fingerprint_hash,
        )

        now = datetime.now(timezone.utc)
        if existing is None:
            existing = ExecutionProfile(
                workspace_id=workspace_id,
                connection_id=connection_id,
                fingerprint_hash=fingerprint_hash,
                first_execution_at=now,
            )

        existing.total_executions += 1
        if succeeded:
            existing.successful_executions += 1
        else:
            existing.failed_executions += 1
            if error_type:
                existing.error_counts[error_type] = (
                    existing.error_counts.get(error_type, 0) + 1
                )

        existing.total_input_tokens += input_tokens
        existing.total_output_tokens += output_tokens
        existing.total_cost_usd += cost_usd
        existing.total_duration_ms += duration_ms
        existing.last_execution_at = now

        # Latency aggregates
        if duration_ms > 0:
            if (
                existing.min_latency_ms is None
                or duration_ms < existing.min_latency_ms
            ):
                existing.min_latency_ms = duration_ms
            if (
                existing.max_latency_ms is None
                or duration_ms > existing.max_latency_ms
            ):
                existing.max_latency_ms = duration_ms
            # Running mean
            if existing.avg_latency_ms is None:
                existing.avg_latency_ms = float(duration_ms)
            else:
                n = existing.total_executions
                existing.avg_latency_ms = (
                    (existing.avg_latency_ms * (n - 1) + duration_ms) / n
                )

        return await self._store.upsert_execution(existing)

    async def get(
        self, *, workspace_id: str, connection_id: str, fingerprint_hash: str,
    ) -> ExecutionProfile | None:
        return await self._store.get_execution(
            workspace_id=workspace_id,
            connection_id=connection_id,
            fingerprint_hash=fingerprint_hash,
        )


# ---------------------------------------------------------------------------
# Registry facade
# ---------------------------------------------------------------------------

class ProfileRegistry:
    """
    Facade over all three profile services.

    Enforces the critical rule: when returning benchmark evidence to a
    user, mark it as reused if it did not originate from the user's own
    connection.
    """

    def __init__(self, store: ProfileStore | None = None) -> None:
        self._store = store or InMemoryProfileStore()
        self.shared = SharedProfileService(self._store)
        self.connection = ConnectionProfileService(self._store)
        self.execution = ExecutionProfileService(self._store)

    async def get_evidence_for_user(
        self,
        *,
        workspace_id: str,
        connection_id: str,
        fingerprint_hash: str,
    ) -> dict[str, Any]:
        """
        Return evidence available to the user, clearly flagging
        reused shared evidence vs. fresh connection-specific evidence.
        """
        shared = await self._store.get_shared(fingerprint_hash)
        execution = await self._store.get_execution(
            workspace_id=workspace_id,
            connection_id=connection_id,
            fingerprint_hash=fingerprint_hash,
        )

        shared_entries = (
            shared.benchmark_evidence if shared else []
        )
        reused_entries: list[dict[str, Any]] = []
        fresh_entries: list[dict[str, Any]] = []
        for entry in shared_entries:
            tagged = dict(entry)
            if entry.get("source_connection_id") == connection_id:
                tagged["is_reused_evidence"] = False
                fresh_entries.append(tagged)
            else:
                tagged["is_reused_evidence"] = True
                reused_entries.append(tagged)

        return {
            "fingerprint_hash": fingerprint_hash,
            "fresh_evidence": fresh_entries,
            "reused_evidence": reused_entries,
            "observed_execution_profile": (
                execution.model_dump() if execution else None
            ),
        }