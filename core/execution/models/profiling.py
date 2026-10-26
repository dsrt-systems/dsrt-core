"""
TieredProfilingOrchestrator — Decides and executes the right amount of
profiling for a model/connection pair.

Tiers (spec §6.D):
    Tier 0 — Identify model, reuse applicable shared profile
    Tier 1 — Verify connection + basic capabilities
    Tier 2 — Run selected domain probes
    Tier 3 — Deeper capability profiling
    Tier 4 — Fresh controlled experiment on user's connection

Rules:
    - Never auto-run token-spending tiers (≥2) without explicit user
      authorization.
    - Never advertise reused shared evidence as "fresh" on the user's
      own connection.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from core.execution.models.fingerprint import ModelFingerprint
from core.execution.models.profiles import ProfileRegistry
from core.execution.models.resolver import (
    ModelResolver,
    ResolvedModelConnection,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tier enum
# ---------------------------------------------------------------------------

class ProfilingTier(IntEnum):
    IDENTIFY = 0            # Fingerprint + reuse shared profile
    VERIFY = 1              # Connection + basic capability check
    DOMAIN_PROBE = 2        # Selected domain probes
    DEEP_CAPABILITY = 3     # Deeper capability profiling
    FRESH_EXPERIMENT = 4    # Full controlled experiment

    @property
    def requires_authorization(self) -> bool:
        """Tiers ≥2 spend tokens and must be authorized."""
        return self.value >= self.DOMAIN_PROBE.value


# ---------------------------------------------------------------------------
# Request / result / decision
# ---------------------------------------------------------------------------

class ProfilingRequest(BaseModel):
    """A profiling request from the user or system."""

    request_id: str = Field(default_factory=lambda: str(uuid4()))
    workspace_id: str
    connection_id: str
    model_id: str
    requested_tier: ProfilingTier = ProfilingTier.IDENTIFY
    user_authorized_tiers: list[int] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    reason: str = ""
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def is_authorized_for(self, tier: ProfilingTier) -> bool:
        if not tier.requires_authorization:
            return True
        return int(tier) in self.user_authorized_tiers


class ProfilingDecision(BaseModel):
    """
    What the orchestrator decided to do before executing anything.

    Returned to the UI so the user can see which tiers will run,
    which require authorization, and which were skipped.
    """

    request_id: str
    planned_tiers: list[int] = Field(default_factory=list)
    skipped_tiers: list[int] = Field(default_factory=list)
    skip_reasons: dict[str, str] = Field(default_factory=dict)
    requires_user_authorization: list[int] = Field(default_factory=list)
    estimated_cost_usd: float | None = None


class ProfilingTierResult(BaseModel):
    tier: int
    tier_name: str
    status: str  # EXECUTED, SKIPPED, UNAUTHORIZED, FAILED
    details: dict[str, Any] = Field(default_factory=dict)
    cost_usd: float = 0.0
    duration_ms: int = 0
    error: str | None = None


class ProfilingResult(BaseModel):
    """Final result of a profiling run."""

    request_id: str
    workspace_id: str
    connection_id: str
    fingerprint: ModelFingerprint | None = None
    resolved_connection: ResolvedModelConnection | None = None
    tier_results: list[ProfilingTierResult] = Field(default_factory=list)
    highest_tier_executed: int = -1
    reused_shared_profile: bool = False
    total_cost_usd: float = 0.0
    completed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class TieredProfilingOrchestrator:
    """
    Runs the appropriate profiling tiers for a model/connection pair.

    Dependency-injected: takes a resolver and a profile registry. For
    tier 2+ it delegates to pluggable probe implementations (not
    hard-coded here — probes are domain-specific and will be registered
    by C8/C11 integration).
    """

    def __init__(
        self,
        *,
        resolver: ModelResolver,
        registry: ProfileRegistry,
    ) -> None:
        self._resolver = resolver
        self._registry = registry

    # -- planning -----------------------------------------------------------

    def plan(self, request: ProfilingRequest) -> ProfilingDecision:
        """
        Decide which tiers will run.

        Always includes tiers 0 and 1 (no cost). Includes tiers 2+ only
        if the user has pre-authorized them.
        """
        planned: list[int] = []
        skipped: list[int] = []
        reasons: dict[str, str] = {}
        needs_auth: list[int] = []

        for tier in ProfilingTier:
            if int(tier) > int(request.requested_tier):
                skipped.append(int(tier))
                reasons[str(int(tier))] = (
                    "Beyond requested_tier"
                )
                continue

            if tier.requires_authorization and not request.is_authorized_for(tier):
                skipped.append(int(tier))
                reasons[str(int(tier))] = (
                    "Requires explicit user authorization"
                )
                needs_auth.append(int(tier))
                continue

            planned.append(int(tier))

        return ProfilingDecision(
            request_id=request.request_id,
            planned_tiers=planned,
            skipped_tiers=skipped,
            skip_reasons=reasons,
            requires_user_authorization=needs_auth,
            estimated_cost_usd=None,  # Set by probe registry in future
        )

    # -- execution ----------------------------------------------------------

    async def execute(
        self, request: ProfilingRequest,
    ) -> ProfilingResult:
        """Execute the planned tiers in order."""
        decision = self.plan(request)
        result = ProfilingResult(
            request_id=request.request_id,
            workspace_id=request.workspace_id,
            connection_id=request.connection_id,
        )

        resolved: ResolvedModelConnection | None = None

        for tier_value in sorted(decision.planned_tiers):
            tier = ProfilingTier(tier_value)
            try:
                tier_result = await self._run_tier(
                    tier=tier,
                    request=request,
                    resolved_so_far=resolved,
                    result=result,
                )
                result.tier_results.append(tier_result)
                if tier_result.status == "EXECUTED":
                    result.highest_tier_executed = max(
                        result.highest_tier_executed, int(tier)
                    )
                    result.total_cost_usd += tier_result.cost_usd
                    # Carry resolved connection forward
                    if tier == ProfilingTier.IDENTIFY:
                        resolved = (
                            tier_result.details.get("resolved_connection")
                        )
                        if resolved:
                            result.resolved_connection = resolved
                            result.fingerprint = resolved.fingerprint
            except Exception as exc:
                logger.exception(
                    "Profiling tier %s failed.", tier.name
                )
                result.tier_results.append(
                    ProfilingTierResult(
                        tier=int(tier),
                        tier_name=tier.name,
                        status="FAILED",
                        error=str(exc),
                    )
                )
                # Do not continue past a failed tier
                break

        # Mark unauthorized tiers in the result
        for tier_value in decision.requires_user_authorization:
            tier = ProfilingTier(tier_value)
            result.tier_results.append(
                ProfilingTierResult(
                    tier=int(tier),
                    tier_name=tier.name,
                    status="UNAUTHORIZED",
                )
            )

        return result

    # -- tier implementations ----------------------------------------------

    async def _run_tier(
        self,
        *,
        tier: ProfilingTier,
        request: ProfilingRequest,
        resolved_so_far: ResolvedModelConnection | None,
        result: ProfilingResult,
    ) -> ProfilingTierResult:
        if tier == ProfilingTier.IDENTIFY:
            return await self._tier_identify(request, result)
        if tier == ProfilingTier.VERIFY:
            return await self._tier_verify(request, resolved_so_far)
        if tier == ProfilingTier.DOMAIN_PROBE:
            return self._tier_not_implemented(tier)
        if tier == ProfilingTier.DEEP_CAPABILITY:
            return self._tier_not_implemented(tier)
        if tier == ProfilingTier.FRESH_EXPERIMENT:
            return self._tier_not_implemented(tier)
        raise ValueError(f"Unknown profiling tier: {tier}")

    async def _tier_identify(
        self,
        request: ProfilingRequest,
        result: ProfilingResult,
    ) -> ProfilingTierResult:
        """
        Tier 0 — Resolve model, build fingerprint, reuse shared profile.
        Zero token cost (metadata only).
        """
        resolved = await self._resolver.resolve(
            workspace_id=request.workspace_id,
            connection_id=request.connection_id,
            model_id=request.model_id,
            required_capabilities=request.required_capabilities,
            verify_reachable=False,
        )
        shared_profile, created = await self._registry.shared.get_or_create(
            resolved.fingerprint
        )
        result.reused_shared_profile = not created
        return ProfilingTierResult(
            tier=int(ProfilingTier.IDENTIFY),
            tier_name=ProfilingTier.IDENTIFY.name,
            status="EXECUTED",
            cost_usd=0.0,
            details={
                "fingerprint_hash": resolved.fingerprint.fingerprint_hash,
                "fingerprint_display": resolved.fingerprint.display_name(),
                "shared_profile_id": shared_profile.profile_id,
                "shared_profile_reused": not created,
                "evidence_count": shared_profile.evidence_count,
                "resolved_connection": resolved,
            },
        )

    async def _tier_verify(
        self,
        request: ProfilingRequest,
        resolved_so_far: ResolvedModelConnection | None,
    ) -> ProfilingTierResult:
        """
        Tier 1 — Verify reachability and basic capability match.
        Minimal/zero token cost.
        """
        resolved = await self._resolver.resolve(
            workspace_id=request.workspace_id,
            connection_id=request.connection_id,
            model_id=request.model_id,
            required_capabilities=request.required_capabilities,
            verify_reachable=True,
        )
        return ProfilingTierResult(
            tier=int(ProfilingTier.VERIFY),
            tier_name=ProfilingTier.VERIFY.name,
            status="EXECUTED",
            cost_usd=0.0,
            duration_ms=resolved.reachability_latency_ms or 0,
            details={
                "reachable": resolved.reachable,
                "latency_ms": resolved.reachability_latency_ms,
                "capabilities": resolved.capabilities,
                "supports_streaming": resolved.supports_streaming,
                "supports_tool_use": resolved.supports_tool_use,
                "context_window_tokens": resolved.context_window_tokens,
            },
        )

    @staticmethod
    def _tier_not_implemented(tier: ProfilingTier) -> ProfilingTierResult:
        """
        Tiers 2–4 require probe registries supplied by C8/C11 integration.
        Returning a SKIPPED result keeps the orchestrator honest rather
        than silently claiming success.
        """
        return ProfilingTierResult(
            tier=int(tier),
            tier_name=tier.name,
            status="SKIPPED",
            details={
                "reason": (
                    "No probe registry provided for this tier. "
                    "Register probes via C8/C11 integration to enable."
                ),
            },
        )