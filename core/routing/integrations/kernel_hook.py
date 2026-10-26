"""C9.10 - Kernel Routing Hook."""
from __future__ import annotations

from core.routing.contracts import (
    AggregatedEvidence,
    RouteCandidate,
    RouteDecision,
    RoutingPolicy,
    RoutingProfile,
    TaskRequirements,
)
from core.routing.enums import RoutingStatus
from core.routing.cache.manager import RouteCacheManager
from core.routing.selector.router import IntelligenceRouter


class KernelRoutingHook:
    def __init__(
        self,
        router: IntelligenceRouter,
        cache: RouteCacheManager | None = None,
    ) -> None:
        self._router = router
        self._cache = cache

    def resolve_execution_route(
        self,
        requirements: TaskRequirements,
        candidates: list[RouteCandidate],
        policy: RoutingPolicy | None = None,
        profile: RoutingProfile | None = None,
        evidence_map: dict[str, AggregatedEvidence] | None = None,
    ) -> RouteDecision:
        cache_key = None
        if self._cache is not None:
            cache_key = self._cache.compute_cache_key(
                requirements_hash=requirements.requirements_hash(),
                policy_id=policy.policy_id if policy else None,
                policy_version=policy.version if policy else None,
                profile_id=profile.profile_id if profile else None,
            )
            cached_route = self._cache.get(cache_key)
            if cached_route is not None:
                return RouteDecision(
                    decision_id=f"cached_{cache_key[:16]}",
                    task_id=requirements.task_id,
                    status=RoutingStatus.COMPLETED,
                    requirements=requirements,
                    selected_route=cached_route,
                    decision_reason={"source": "cache", "cache_key": cache_key},
                )

        decision = self._router.route(
            requirements=requirements,
            candidates=candidates,
            policy=policy,
            profile=profile,
            evidence_map=evidence_map,
        )

        if self._cache is not None and cache_key and decision.selected_route:
            self._cache.put(cache_key, decision.selected_route, decision.decision_id)

        return decision

    def invalidate_route(self, cache_key: str) -> bool:
        if self._cache is None:
            return False
        return self._cache.invalidate(cache_key)
