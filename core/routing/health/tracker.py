# core/routing/health/tracker.py
"""
C9 Provider Health Tracker (§45–46).

Maintains operational provider state — this is about *availability*,
not quality.  A model can be high-quality but temporarily unavailable.

Health states:
  AVAILABLE    — operating normally
  DEGRADED     — elevated latency or error rate
  RATE_LIMITED — hitting rate limits
  UNAVAILABLE  — not responding
  UNKNOWN      — no recent observations
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from core.routing.contracts import ProviderHealthState
from core.routing.enums import ProviderHealthStatus


class ProviderHealthTracker:
    """Tracks operational health of LLM providers (§45–46).

    Health is determined by recent success/failure observations,
    latency windows, and error rates.  This is *operational* state,
    not a quality judgment.

    Args:
        health_ttl_seconds: How long a health observation remains
            valid before reverting to UNKNOWN.
        degraded_error_threshold: Error rate above which a provider
            is considered DEGRADED (0.0–1.0).
        degraded_latency_ms: P99 latency above which a provider
            is considered DEGRADED (milliseconds).
    """

    def __init__(
        self,
        health_ttl_seconds: float = 300.0,  # 5 minutes
        degraded_error_threshold: float = 0.1,
        degraded_latency_ms: float = 10000.0,
    ) -> None:
        if health_ttl_seconds <= 0:
            raise ValueError(
                f"health_ttl_seconds must be > 0, got {health_ttl_seconds}"
            )
        self._ttl = health_ttl_seconds
        self._error_thresh = degraded_error_threshold
        self._latency_thresh = degraded_latency_ms
        self._states: dict[str, ProviderHealthState] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_success(
        self,
        provider_id: str,
        latency_ms: float | None = None,
        now: datetime | None = None,
    ) -> ProviderHealthState:
        """Record a successful provider interaction.

        Args:
            provider_id: Provider identifier.
            latency_ms: Response latency in milliseconds.
            now: Override current time for testing.

        Returns:
            Updated ``ProviderHealthState``.
        """
        ref = now or datetime.now(timezone.utc)
        state = self._get_or_create(provider_id, ref)

        state.last_success_at = ref
        state.observed_at = ref
        state.expires_at = ref + timedelta(seconds=self._ttl)

        if latency_ms is not None:
            state.latency_p50_ms = latency_ms  # simplified
            state.latency_p99_ms = latency_ms * 1.5

        self._recompute_status(state, ref)
        self._states[provider_id] = state
        return state

    def record_failure(
        self,
        provider_id: str,
        error_rate: float | None = None,
        now: datetime | None = None,
    ) -> ProviderHealthState:
        """Record a failed provider interaction.

        Args:
            provider_id: Provider identifier.
            error_rate: Current error rate (0.0–1.0).
            now: Override current time for testing.

        Returns:
            Updated ``ProviderHealthState``.
        """
        ref = now or datetime.now(timezone.utc)
        state = self._get_or_create(provider_id, ref)

        state.last_failure_at = ref
        state.observed_at = ref
        state.expires_at = ref + timedelta(seconds=self._ttl)

        if error_rate is not None:
            state.error_rate = error_rate

        self._recompute_status(state, ref)
        self._states[provider_id] = state
        return state

    def record_rate_limit(
        self,
        provider_id: str,
        now: datetime | None = None,
    ) -> ProviderHealthState:
        """Record that a provider returned a rate limit response."""
        ref = now or datetime.now(timezone.utc)
        state = self._get_or_create(provider_id, ref)
        state.status = ProviderHealthStatus.RATE_LIMITED
        state.last_failure_at = ref
        state.observed_at = ref
        state.expires_at = ref + timedelta(seconds=self._ttl)
        self._states[provider_id] = state
        return state

    def get_health(
        self,
        provider_id: str,
        now: datetime | None = None,
    ) -> ProviderHealthState:
        """Get current health state for a provider.

        If the observation has expired, returns UNKNOWN status.
        If no observation exists, returns a default UNKNOWN state.
        """
        ref = now or datetime.now(timezone.utc)
        state = self._states.get(provider_id)

        if state is None:
            return ProviderHealthState(
                provider_id=provider_id,
                status=ProviderHealthStatus.UNKNOWN,
                observed_at=ref,
            )

        # Check expiry
        if state.expires_at and ref > state.expires_at:
            state.status = ProviderHealthStatus.UNKNOWN
            state.expires_at = None

        return state

    def get_all_health(
        self,
        now: datetime | None = None,
    ) -> dict[str, ProviderHealthState]:
        """Get health states for all tracked providers."""
        return {
            pid: self.get_health(pid, now)
            for pid in self._states
        }

    def is_available(
        self,
        provider_id: str,
        now: datetime | None = None,
    ) -> bool:
        """Quick check if a provider is available for routing."""
        return self.get_health(provider_id, now).is_available

    def filter_available(
        self,
        provider_ids: list[str],
        now: datetime | None = None,
    ) -> list[str]:
        """Filter a list of providers to only available ones."""
        return [
            pid for pid in provider_ids
            if self.is_available(pid, now)
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_or_create(
        self, provider_id: str, now: datetime
    ) -> ProviderHealthState:
        """Get existing state or create a new one."""
        existing = self._states.get(provider_id)
        if existing is not None:
            return existing
        return ProviderHealthState(
            provider_id=provider_id,
            status=ProviderHealthStatus.UNKNOWN,
            observed_at=now,
        )

    def _recompute_status(
        self, state: ProviderHealthState, now: datetime
    ) -> None:
        """Recompute status from error rate and latency."""
        # Check error rate
        if state.error_rate is not None:
            if state.error_rate >= 0.5:
                state.status = ProviderHealthStatus.UNAVAILABLE
                return
            if state.error_rate >= self._error_thresh:
                state.status = ProviderHealthStatus.DEGRADED
                return

        # Check latency
        if (
            state.latency_p99_ms is not None
            and state.latency_p99_ms > self._latency_thresh
        ):
            state.status = ProviderHealthStatus.DEGRADED
            return

        # Default: available if we have a recent success
        if state.last_success_at is not None:
            state.status = ProviderHealthStatus.AVAILABLE
        elif state.last_failure_at is not None:
            state.status = ProviderHealthStatus.UNAVAILABLE