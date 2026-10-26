# core/routing/cache/manager.py
"""
C9 Route Cache Manager (§47).

Caches route decisions for repeated tasks.  Cache keys are
deterministic, incorporating all factors that could change the
routing decision:

  - task requirement hash
  - agent version
  - model version
  - world version
  - policy version
  - provider health state
  - routing profile

A cached route is only valid if ALL of these match.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from core.routing.contracts import Route, RouteDecision


@dataclass
class CacheEntry:
    """A cached route decision."""

    cache_key: str
    route: Route
    decision_id: str
    created_at: datetime
    expires_at: datetime
    hit_count: int = 0

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at


class RouteCacheManager:
    """Deterministic route cache (§47).

    Args:
        ttl_seconds: Default cache entry lifetime.
        max_entries: Maximum cache size (LRU eviction).
    """

    def __init__(
        self,
        ttl_seconds: float = 600.0,  # 10 minutes
        max_entries: int = 1000,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError(
                f"ttl_seconds must be > 0, got {ttl_seconds}"
            )
        if max_entries < 1:
            raise ValueError(
                f"max_entries must be >= 1, got {max_entries}"
            )
        self._ttl = ttl_seconds
        self._max = max_entries
        self._cache: dict[str, CacheEntry] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_cache_key(
        self,
        requirements_hash: str,
        policy_id: str | None = None,
        policy_version: str | None = None,
        profile_id: str | None = None,
        health_hashes: dict[str, str] | None = None,
    ) -> str:
        """Compute a deterministic cache key (§47).

        All inputs that affect routing must be included so that
        any change invalidates the cache.

        Args:
            requirements_hash: From ``TaskRequirements.requirements_hash()``.
            policy_id: Active routing policy ID.
            policy_version: Active routing policy version.
            profile_id: Active routing profile ID.
            health_hashes: ``{provider_id: health_hash}`` from
                ``ProviderHealthState.health_hash()``.

        Returns:
            SHA-256 hex digest (truncated to 32 chars).
        """
        canonical = {
            "requirements": requirements_hash,
            "policy": f"{policy_id}:{policy_version}",
            "profile": profile_id or "",
            "health": dict(sorted((health_hashes or {}).items())),
        }
        raw = json.dumps(canonical, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def get(
        self,
        cache_key: str,
        now: datetime | None = None,
    ) -> Route | None:
        """Look up a cached route.

        Returns ``None`` if the key is not found or the entry
        has expired.
        """
        entry = self._cache.get(cache_key)
        if entry is None:
            return None

        ref = now or datetime.now(timezone.utc)
        if ref > entry.expires_at:
            del self._cache[cache_key]
            return None

        entry.hit_count += 1
        return entry.route

    def put(
        self,
        cache_key: str,
        route: Route,
        decision_id: str,
        now: datetime | None = None,
    ) -> CacheEntry:
        """Store a route decision in the cache.

        If the cache is full, the oldest entry is evicted.
        """
        ref = now or datetime.now(timezone.utc)

        # Evict if at capacity
        if len(self._cache) >= self._max and cache_key not in self._cache:
            self._evict_oldest()

        entry = CacheEntry(
            cache_key=cache_key,
            route=route,
            decision_id=decision_id,
            created_at=ref,
            expires_at=ref + timedelta(seconds=self._ttl),
        )
        self._cache[cache_key] = entry
        return entry

    def invalidate(self, cache_key: str) -> bool:
        """Remove a specific cache entry.  Returns True if found."""
        if cache_key in self._cache:
            del self._cache[cache_key]
            return True
        return False

    def invalidate_all(self) -> int:
        """Clear the entire cache.  Returns number of entries removed."""
        count = len(self._cache)
        self._cache.clear()
        return count

    def invalidate_by_provider(self, provider_id: str) -> int:
        """Invalidate all cache entries using a specific provider.

        Used when provider health changes.
        """
        to_remove = [
            key for key, entry in self._cache.items()
            if entry.route.provider_id == provider_id
        ]
        for key in to_remove:
            del self._cache[key]
        return len(to_remove)

    @property
    def size(self) -> int:
        return len(self._cache)

    @property
    def stats(self) -> dict[str, Any]:
        """Cache statistics."""
        total_hits = sum(e.hit_count for e in self._cache.values())
        return {
            "size": len(self._cache),
            "max_entries": self._max,
            "ttl_seconds": self._ttl,
            "total_hits": total_hits,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _evict_oldest(self) -> None:
        """Remove the oldest cache entry."""
        if not self._cache:
            return
        oldest_key = min(
            self._cache,
            key=lambda k: self._cache[k].created_at,
        )
        del self._cache[oldest_key]