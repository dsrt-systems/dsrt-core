# tests/test_c9_health_cache.py
"""
C9.8 Provider Health & Route Cache — comprehensive tests.

Covers:
  - ProviderHealthTracker (§45–46)
  - RouteCacheManager (§47)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.routing.contracts import ProviderHealthState, Route
from core.routing.enums import ProviderHealthStatus
from core.routing.cache.manager import CacheEntry, RouteCacheManager
from core.routing.health.tracker import ProviderHealthTracker


# ── Helpers ────────────────────────────────────────────────────────────

NOW = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


def _route(provider: str = "prov-1") -> Route:
    return Route(
        agent_id="agent-1",
        agent_version_id="av-1",
        model_id="model-a",
        model_version_id="mv-1",
        provider_id=provider,
    )


# ═══════════════════════════════════════════════════════════════════════
# ProviderHealthTracker
# ═══════════════════════════════════════════════════════════════════════

class TestProviderHealthTracker:

    def setup_method(self) -> None:
        self.tracker = ProviderHealthTracker(health_ttl_seconds=300)

    def test_unknown_by_default(self) -> None:
        h = self.tracker.get_health("prov-1", now=NOW)
        assert h.status == ProviderHealthStatus.UNKNOWN
        assert not h.is_available

    def test_record_success(self) -> None:
        h = self.tracker.record_success("prov-1", latency_ms=200, now=NOW)
        assert h.status == ProviderHealthStatus.AVAILABLE
        assert h.is_available
        assert h.is_healthy
        assert h.last_success_at == NOW

    def test_record_failure_high_error(self) -> None:
        h = self.tracker.record_failure("prov-1", error_rate=0.6, now=NOW)
        assert h.status == ProviderHealthStatus.UNAVAILABLE
        assert not h.is_available

    def test_record_failure_degraded(self) -> None:
        h = self.tracker.record_failure("prov-1", error_rate=0.15, now=NOW)
        assert h.status == ProviderHealthStatus.DEGRADED
        assert h.is_available  # degraded is still available

    def test_record_rate_limit(self) -> None:
        h = self.tracker.record_rate_limit("prov-1", now=NOW)
        assert h.status == ProviderHealthStatus.RATE_LIMITED
        assert not h.is_available

    def test_health_expiry(self) -> None:
        self.tracker.record_success("prov-1", now=NOW)
        h = self.tracker.get_health(
            "prov-1", now=NOW + timedelta(seconds=400),
        )
        assert h.status == ProviderHealthStatus.UNKNOWN

    def test_is_available_helper(self) -> None:
        assert not self.tracker.is_available("prov-1", now=NOW)
        self.tracker.record_success("prov-1", now=NOW)
        assert self.tracker.is_available("prov-1", now=NOW)

    def test_filter_available(self) -> None:
        self.tracker.record_success("prov-1", now=NOW)
        self.tracker.record_failure("prov-2", error_rate=0.8, now=NOW)
        self.tracker.record_success("prov-3", now=NOW)
        result = self.tracker.filter_available(
            ["prov-1", "prov-2", "prov-3"], now=NOW,
        )
        assert "prov-1" in result
        assert "prov-3" in result
        assert "prov-2" not in result

    def test_get_all_health(self) -> None:
        self.tracker.record_success("prov-1", now=NOW)
        self.tracker.record_success("prov-2", now=NOW)
        all_h = self.tracker.get_all_health(now=NOW)
        assert len(all_h) == 2

    def test_latency_degraded(self) -> None:
        h = self.tracker.record_success(
            "prov-1", latency_ms=8000, now=NOW,
        )
        # p99 = 8000 * 1.5 = 12000 > 10000 threshold
        assert h.status == ProviderHealthStatus.DEGRADED

    def test_invalid_ttl_raises(self) -> None:
        with pytest.raises(ValueError, match="health_ttl"):
            ProviderHealthTracker(health_ttl_seconds=0)

    def test_success_then_failure(self) -> None:
        self.tracker.record_success("prov-1", now=NOW)
        h = self.tracker.record_failure("prov-1", error_rate=0.6, now=NOW)
        assert h.status == ProviderHealthStatus.UNAVAILABLE


# ═══════════════════════════════════════════════════════════════════════
# RouteCacheManager
# ═══════════════════════════════════════════════════════════════════════

class TestRouteCacheManager:

    def setup_method(self) -> None:
        self.cache = RouteCacheManager(ttl_seconds=600, max_entries=10)

    def test_compute_cache_key_deterministic(self) -> None:
        k1 = self.cache.compute_cache_key("req-hash-1", "pol-1", "1")
        k2 = self.cache.compute_cache_key("req-hash-1", "pol-1", "1")
        assert k1 == k2
        assert len(k1) == 32

    def test_cache_key_changes_with_input(self) -> None:
        k1 = self.cache.compute_cache_key("req-1", "pol-1", "1")
        k2 = self.cache.compute_cache_key("req-2", "pol-1", "1")
        k3 = self.cache.compute_cache_key("req-1", "pol-2", "1")
        assert k1 != k2
        assert k1 != k3

    def test_cache_key_includes_health(self) -> None:
        k1 = self.cache.compute_cache_key(
            "req-1", "pol-1", "1",
            health_hashes={"prov-1": "abc"},
        )
        k2 = self.cache.compute_cache_key(
            "req-1", "pol-1", "1",
            health_hashes={"prov-1": "xyz"},
        )
        assert k1 != k2

    def test_put_and_get(self) -> None:
        key = self.cache.compute_cache_key("req-1")
        route = _route()
        self.cache.put(key, route, "dec-1", now=NOW)
        result = self.cache.get(key, now=NOW)
        assert result is not None
        assert result.model_id == "model-a"

    def test_get_miss(self) -> None:
        assert self.cache.get("nonexistent", now=NOW) is None

    def test_get_expired(self) -> None:
        key = self.cache.compute_cache_key("req-1")
        self.cache.put(key, _route(), "dec-1", now=NOW)
        result = self.cache.get(
            key, now=NOW + timedelta(seconds=700),
        )
        assert result is None

    def test_hit_count_increments(self) -> None:
        key = self.cache.compute_cache_key("req-1")
        self.cache.put(key, _route(), "dec-1", now=NOW)
        self.cache.get(key, now=NOW)
        self.cache.get(key, now=NOW)
        entry = self.cache._cache[key]
        assert entry.hit_count == 2

    def test_invalidate(self) -> None:
        key = self.cache.compute_cache_key("req-1")
        self.cache.put(key, _route(), "dec-1", now=NOW)
        assert self.cache.invalidate(key) is True
        assert self.cache.get(key, now=NOW) is None
        assert self.cache.invalidate(key) is False

    def test_invalidate_all(self) -> None:
        for i in range(3):
            key = self.cache.compute_cache_key(f"req-{i}")
            self.cache.put(key, _route(), f"dec-{i}", now=NOW)
        assert self.cache.size == 3
        count = self.cache.invalidate_all()
        assert count == 3
        assert self.cache.size == 0

    def test_invalidate_by_provider(self) -> None:
        key1 = self.cache.compute_cache_key("req-1")
        key2 = self.cache.compute_cache_key("req-2")
        self.cache.put(key1, _route("prov-1"), "dec-1", now=NOW)
        self.cache.put(key2, _route("prov-2"), "dec-2", now=NOW)
        count = self.cache.invalidate_by_provider("prov-1")
        assert count == 1
        assert self.cache.size == 1

    def test_eviction(self) -> None:
        cache = RouteCacheManager(ttl_seconds=600, max_entries=2)
        cache.put("k1", _route(), "d1", now=NOW)
        cache.put("k2", _route(), "d2", now=NOW + timedelta(seconds=1))
        cache.put("k3", _route(), "d3", now=NOW + timedelta(seconds=2))
        assert cache.size == 2
        assert cache.get("k1", now=NOW) is None  # evicted

    def test_stats(self) -> None:
        key = self.cache.compute_cache_key("req-1")
        self.cache.put(key, _route(), "dec-1", now=NOW)
        self.cache.get(key, now=NOW)
        s = self.cache.stats
        assert s["size"] == 1
        assert s["total_hits"] == 1
        assert s["max_entries"] == 10

    def test_invalid_ttl_raises(self) -> None:
        with pytest.raises(ValueError, match="ttl_seconds"):
            RouteCacheManager(ttl_seconds=0)

    def test_invalid_max_raises(self) -> None:
        with pytest.raises(ValueError, match="max_entries"):
            RouteCacheManager(max_entries=0)