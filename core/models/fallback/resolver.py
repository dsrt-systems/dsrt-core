"""
Fallback Resolver (C2 §28).

When the primary model fails permanently, the fallback resolver uses the
Model Router to find the next eligible model that satisfies the same
capability requirements and policy constraints.
"""

from __future__ import annotations

from core.models.router import ModelRouter, RouteCandidateSelection
from core.observability.logging import get_logger
from schemas.domain import ModelPolicy, ModelRequest, ModelRequirements


logger = get_logger("dsrt.models.fallback")


class FallbackResolver:
    """Resolves a fallback model when the primary fails."""

    def __init__(self, router: ModelRouter) -> None:
        self._router = router

    async def resolve_fallback(
        self,
        request: ModelRequest,
        failed_model_id: str,
        failed_provider_id: str,
    ) -> RouteCandidateSelection | None:
        """Attempt to find a fallback model by blocking the failed model and re-routing."""

        # Build a modified policy that explicitly blocks the failed model
        original_policy = request.model_policy or ModelPolicy()
        blocked = list(original_policy.blocked_models or [])
        if failed_model_id not in blocked:
            blocked.append(failed_model_id)

        fallback_policy = ModelPolicy(
            policy_id=original_policy.policy_id,
            allowed_providers=list(original_policy.allowed_providers or []),
            blocked_providers=list(original_policy.blocked_providers or []),
            allowed_models=list(original_policy.allowed_models or []),
            blocked_models=blocked,
            preferred_models=list(original_policy.fallback_models or []),
            fallback_models=[],
            allow_byok=original_policy.allow_byok,
            allow_managed=original_policy.allow_managed,
            allow_enterprise=original_policy.allow_enterprise,
            maximum_cost_usd=original_policy.maximum_cost_usd,
            maximum_latency_ms=original_policy.maximum_latency_ms,
            prefer_lower_cost=original_policy.prefer_lower_cost,
            prefer_lower_latency=original_policy.prefer_lower_latency,
        )

        try:
            selection = await self._router.route(
                request,
                policy=fallback_policy,
                requirements=request.requirements,
            )
            logger.info(
                "fallback_resolved",
                request_id=request.request_id,
                failed_model=failed_model_id,
                fallback_model=selection.selected_model.id,
                fallback_provider=selection.selected_provider.id,
            )
            return selection

        except Exception as e:
            logger.warning(
                "fallback_resolution_failed",
                request_id=request.request_id,
                failed_model=failed_model_id,
                error=str(e),
            )
            return None