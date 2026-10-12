"""
Model Router — Deterministic Constraint Resolution Engine (C2 §17-19, §31-33).

Evaluates hard constraints and policy preferences to select the optimal model
for a request and produces an auditable RoutingDecision.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from core.api.errors.exceptions import DSRTError, NotFoundError
from core.observability.logging import get_logger
from core.repositories import ProviderRepository
from core.storage.identifiers import IdPrefix, new_id
from schemas.domain import (
    Model,
    ModelPolicy,
    ModelRequest,
    ModelRequirements,
    Provider,
    RejectedCandidate,
    RoutingDecision,
    RoutingReasonCode,
)


logger = get_logger("dsrt.models.router")


@dataclass(frozen=True)
class RouteCandidateSelection:
    """The outcome of a routing resolution."""

    selected_model: Model
    selected_provider: Provider
    decision: RoutingDecision


class ModelRouter:
    """Deterministic Model Router."""

    def __init__(self, provider_repo: ProviderRepository) -> None:
        self._repo = provider_repo

    async def route(
        self,
        request: ModelRequest,
        policy: ModelPolicy | None = None,
        requirements: ModelRequirements | None = None,
    ) -> RouteCandidateSelection:
        """Route a ModelRequest to an optimal available model (C2 §17)."""
        start_time = time.perf_counter()
        
        # Merge request-level policy/requirements with parameters
        effective_policy = policy or request.model_policy or ModelPolicy()
        effective_reqs = requirements or request.requirements or ModelRequirements()

        # Fetch all active models and providers
        all_models_orm = await self._repo.list_models(active_only=True)
        if not all_models_orm:
            raise NotFoundError("No active models registered in Model Fabric.")

        all_providers_orm = await self._repo.list_providers()
        provider_map: dict[str, Provider] = {
            p.id: Provider.model_validate(p, from_attributes=True)
            for p in all_providers_orm
        }

        candidates_considered: list[str] = []
        eligible_candidates: list[tuple[Model, Provider, list[RoutingReasonCode]]] = []
        rejected_candidates: list[RejectedCandidate] = []

        # Iterate and evaluate each registered model
        for m_orm in all_models_orm:
            # Unpack ORM JSON blob into Pydantic Model
            data = m_orm.capabilities or {}
            model = Model(
                id=m_orm.id,
                provider_id=m_orm.provider_id,
                slug=m_orm.slug,
                name=m_orm.name,
                model_identifier=m_orm.model_identifier,
                version=m_orm.version,
                status=m_orm.status,
                capabilities=data.get("capabilities", {}),
                context_config=data.get("context_config", {"max_input_tokens": 1, "max_output_tokens": 1}),
                pricing_config=data.get("pricing_config", {}),
                metadata=data.get("metadata", {}),
                created_at=m_orm.created_at,
                updated_at=m_orm.updated_at,
            )
            
            provider = provider_map.get(model.provider_id)
            if not provider or provider.status != "active":
                continue

            candidates_considered.append(model.id)
            rejection_reasons: list[RoutingReasonCode] = []
            match_reasons: list[RoutingReasonCode] = []

            # ---------------------------------------------------------------
            # 1. Security / Organization Policy Filtering (C2 §31)
            # ---------------------------------------------------------------
            if effective_policy.blocked_providers and (
                provider.slug in effective_policy.blocked_providers or provider.id in effective_policy.blocked_providers
            ):
                rejection_reasons.append(RoutingReasonCode.POLICY_BLOCKED)

            if effective_policy.allowed_providers and (
                provider.slug not in effective_policy.allowed_providers and provider.id not in effective_policy.allowed_providers
            ):
                rejection_reasons.append(RoutingReasonCode.POLICY_BLOCKED)

            if effective_policy.blocked_models and (
                model.slug in effective_policy.blocked_models or model.id in effective_policy.blocked_models
            ):
                rejection_reasons.append(RoutingReasonCode.POLICY_BLOCKED)

            if effective_policy.allowed_models and (
                model.slug not in effective_policy.allowed_models and model.id not in effective_policy.allowed_models
            ):
                rejection_reasons.append(RoutingReasonCode.POLICY_BLOCKED)

            # ---------------------------------------------------------------
            # 2. Capability Requirements Filtering (C2 §16)
            # ---------------------------------------------------------------
            if request.tools or effective_reqs.supports_tool_calling:
                if not model.capabilities.tool_calling:
                    rejection_reasons.append(RoutingReasonCode.CAPABILITY_MISMATCH)

            if request.response_schema or effective_reqs.supports_structured_output:
                if not model.capabilities.structured_output:
                    rejection_reasons.append(RoutingReasonCode.CAPABILITY_MISMATCH)

            if effective_reqs.supports_vision:
                if not model.capabilities.vision:
                    rejection_reasons.append(RoutingReasonCode.CAPABILITY_MISMATCH)

            if effective_reqs.supports_reasoning:
                if not model.capabilities.reasoning:
                    rejection_reasons.append(RoutingReasonCode.CAPABILITY_MISMATCH)

            # ---------------------------------------------------------------
            # 3. Context Window Filtering (C2 §24)
            # ---------------------------------------------------------------
            if effective_reqs.minimum_context_tokens:
                if model.context_config.max_input_tokens < effective_reqs.minimum_context_tokens:
                    rejection_reasons.append(RoutingReasonCode.CONTEXT_REQUIREMENT_UNMET)

            # ---------------------------------------------------------------
            # 4. Cost Policy Filtering
            # ---------------------------------------------------------------
            if effective_policy.maximum_cost_usd is not None:
                # Estimate cost per 1M input tokens
                if model.pricing_config.input_cost_per_m > effective_policy.maximum_cost_usd:
                    rejection_reasons.append(RoutingReasonCode.EXCEEDS_COST_LIMIT)

            # Decision record for candidate
            if rejection_reasons:
                rejected_candidates.append(
                    RejectedCandidate(
                        model_id=model.id,
                        provider_id=provider.id,
                        model_identifier=model.model_identifier,
                        reason_codes=list(set(rejection_reasons)),
                    )
                )
            else:
                match_reasons.extend([
                    RoutingReasonCode.CAPABILITY_MATCH,
                    RoutingReasonCode.CONTEXT_REQUIREMENT_MET,
                    RoutingReasonCode.HEALTHY,
                    RoutingReasonCode.POLICY_ALLOWED,
                ])
                eligible_candidates.append((model, provider, match_reasons))

        if not eligible_candidates:
            raise DSRTError(
                "No eligible model candidates satisfied request requirements and policies.",
                metadata={
                    "candidates_considered": len(candidates_considered),
                    "rejected_candidates_count": len(rejected_candidates),
                },
            )

        # -------------------------------------------------------------------
        # 5. Route Selection among eligible candidates
        # -------------------------------------------------------------------
        # Sort based on policy preference (cost vs latency vs preference list)
        def _candidate_sort_key(item: tuple[Model, Provider, list[RoutingReasonCode]]) -> tuple:
            m, p, _ = item
            
            # Explicit preferred models get highest priority
            is_preferred = 0
            if effective_policy.preferred_models:
                if m.slug in effective_policy.preferred_models or m.id in effective_policy.preferred_models:
                    is_preferred = -1  # Sorts first

            cost = m.pricing_config.input_cost_per_m if effective_policy.prefer_lower_cost else 0
            return (is_preferred, cost)

        eligible_candidates.sort(key=_candidate_sort_key)
        selected_model, selected_provider, selected_reasons = eligible_candidates[0]

        decision_latency = int((time.perf_counter() - start_time) * 1000)

        decision = RoutingDecision(
            request_id=request.request_id,
            selected_model_id=selected_model.id,
            selected_provider_id=selected_provider.id,
            selected_model_identifier=selected_model.model_identifier,
            reason_codes=selected_reasons,
            candidates_considered=candidates_considered,
            rejected_candidates=rejected_candidates,
            policy_id=effective_policy.policy_id,
            requirements_snapshot=effective_reqs,
            model_policy_snapshot=effective_policy,
            decided_at=datetime.now(timezone.utc),
            decision_latency_ms=decision_latency,
        )

        logger.info(
            "model_route_selected",
            request_id=request.request_id,
            selected_model=selected_model.slug,
            selected_provider=selected_provider.slug,
            decision_latency_ms=decision_latency,
        )

        return RouteCandidateSelection(
            selected_model=selected_model,
            selected_provider=selected_provider,
            decision=decision,
        )