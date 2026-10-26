# core/routing/evidence/freshness.py
"""
C9 Evidence Freshness Checker (§26).

Determines whether routing evidence is still relevant by checking:
  1. Temporal age — how long since the observation
  2. Version alignment — whether evidence versions match current versions

Old results must not silently masquerade as current evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.routing.contracts import RoutingEvidence


@dataclass(frozen=True)
class FreshnessResult:
    """Outcome of a freshness check."""

    is_fresh: bool
    freshness_weight: float  # 0.0 (completely stale) → 1.0 (perfectly fresh)
    age_hours: float
    version_matches: dict[str, bool] = field(default_factory=dict)
    staleness_reasons: list[str] = field(default_factory=list)


class EvidenceFreshnessChecker:
    """Checks whether routing evidence is still relevant (§26).

    The freshness weight is the product of:
      - **age_weight**: linear decay from 1.0 at age=0 to 0.0 at
        ``max_age_hours``.
      - **version_weight**: multiplied by ``version_mismatch_penalty``
        for every version field that doesn't match.

    Args:
        max_age_hours: Hours after which evidence is fully stale.
        version_mismatch_penalty: Multiplier applied per mismatched
            version field (0.0–1.0).
    """

    def __init__(
        self,
        max_age_hours: float = 168.0,  # 7 days
        version_mismatch_penalty: float = 0.5,
    ) -> None:
        if max_age_hours <= 0:
            raise ValueError(
                f"max_age_hours must be > 0, got {max_age_hours}"
            )
        if not 0.0 <= version_mismatch_penalty <= 1.0:
            raise ValueError(
                f"version_mismatch_penalty must be in [0, 1], "
                f"got {version_mismatch_penalty}"
            )
        self._max_age = max_age_hours
        self._penalty = version_mismatch_penalty

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(
        self,
        evidence: RoutingEvidence,
        *,
        current_model_version: str | None = None,
        current_agent_version: str | None = None,
        current_world_version: str | None = None,
        current_benchmark_version: str | None = None,
        now: datetime | None = None,
    ) -> FreshnessResult:
        """Evaluate freshness of a single ``RoutingEvidence``.

        Args:
            evidence: The evidence to check.
            current_*_version: Current live version strings.  If
                ``None``, that dimension is skipped.
            now: Override current time (for deterministic tests).

        Returns:
            ``FreshnessResult`` with weight and reasons.
        """
        ref = now or datetime.now(timezone.utc)
        age_hours = self._age_hours(evidence.observed_at, ref)
        reasons: list[str] = []

        # ── Age decay ────────────────────────────────────────────
        age_weight = max(0.0, 1.0 - age_hours / self._max_age)
        if age_hours > self._max_age:
            reasons.append(
                f"evidence age {age_hours:.1f}h exceeds "
                f"max {self._max_age:.1f}h"
            )

        # ── Version alignment ────────────────────────────────────
        version_matches: dict[str, bool] = {}
        version_weight = 1.0

        checks = [
            ("model", current_model_version, evidence.model_version),
            ("agent", current_agent_version, evidence.agent_version),
            ("world", current_world_version, evidence.world_version),
            ("benchmark", current_benchmark_version, evidence.benchmark_version),
        ]

        for dim, current, observed in checks:
            if current is None:
                continue  # skip dimension when no current version given
            match = current == observed
            version_matches[dim] = match
            if not match:
                version_weight *= self._penalty
                reasons.append(
                    f"{dim} version mismatch "
                    f"(current={current}, observed={observed})"
                )

        # ── Composite ────────────────────────────────────────────
        weight = round(age_weight * version_weight, 4)
        is_fresh = weight > 0.0 and len(reasons) == 0

        return FreshnessResult(
            is_fresh=is_fresh,
            freshness_weight=weight,
            age_hours=round(age_hours, 2),
            version_matches=version_matches,
            staleness_reasons=reasons,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _age_hours(observed: datetime, now: datetime) -> float:
        """Hours between *observed* and *now* (always ≥ 0)."""
        # Ensure both are offset-aware for subtraction
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        delta = (now - observed).total_seconds()
        return max(0.0, delta / 3600.0)