"""
Phase C11.3: Adaptive Model Selector Main Service

Coordinates task profiles (C11.1), performance profiles (C11.2), feasibility checks,
selection modes (AUTOMATIC, USER_PREFERRED, FIXED), utility scoring, and substitutions.
"""

import uuid
from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from schemas.domain.model_selection import (
    ModelCandidate,
    ModelSelectionMode,
    ModelSelectionRequest,
    ModelSelectionDecision,
    FeasibilityCheckResult,
    SubstitutionReason,
)
from schemas.domain.task_intelligence import TaskProfile
from schemas.domain.performance_intelligence import PerformanceQuery, PerformanceProfile
from core.optimization.model_selection.policy import SelectionPolicyEvaluator
from core.optimization.model_selection.substitution import ModelSubstitutionEngine
from core.optimization.performance_registry import PerformanceIntelligenceRegistry


class AdaptiveModelSelector:
    """
    Main entry point for adaptive model selection.
    Evaluates candidate feasibility, checks hard/soft constraints, computes utility scores,
    and returns deterministic model selection decisions.
    """

    def __init__(
        self,
        policy_evaluator: Optional[SelectionPolicyEvaluator] = None,
        substitution_engine: Optional[ModelSubstitutionEngine] = None,
        performance_registry: Optional[PerformanceIntelligenceRegistry] = None,
    ):
        self.policy_evaluator = policy_evaluator or SelectionPolicyEvaluator()
        self.substitution_engine = substitution_engine or ModelSubstitutionEngine()
        self.performance_registry = performance_registry or PerformanceIntelligenceRegistry()

    def select_model(
        self,
        request: ModelSelectionRequest,
        performance_profiles: Optional[Dict[str, PerformanceProfile]] = None,
        session: Optional[Session] = None,
    ) -> ModelSelectionDecision:
        if not request.available_candidates:
            raise ValueError("available_candidates must contain at least one ModelCandidate")

        # Fallback default tokens if 0
        input_tokens = request.estimated_input_tokens if request.estimated_input_tokens > 0 else 1000
        output_tokens = request.estimated_output_tokens if request.estimated_output_tokens > 0 else 500

        # 1. Evaluate feasibility for all candidate models
        evaluations: List[FeasibilityCheckResult] = []
        candidate_map: Dict[str, ModelCandidate] = {}
        perf_map: Dict[str, PerformanceProfile] = performance_profiles or {}

        for candidate in request.available_candidates:
            candidate_map[candidate.model_id] = candidate

            # Fetch performance profile if not provided in map
            perf_profile = perf_map.get(candidate.model_id)
            if perf_profile is None and session is not None:
                query = PerformanceQuery(
                    model_id=candidate.model_id,
                    domain=request.task_profile.classification.primary_domain.value,
                    intent=request.task_profile.classification.primary_intent.value,
                    complexity_level=request.task_profile.complexity.level.value,
                    min_samples=1,
                )
                perf_profile = self.performance_registry.get_profile(
                    query=query,
                    organization_id=request.organization_id,
                    session=session,
                )

            eval_res = self._check_feasibility(
                candidate=candidate,
                task_profile=request.task_profile,
                estimated_input_tokens=input_tokens,
                estimated_output_tokens=output_tokens,
                perf_profile=perf_profile,
            )
            evaluations.append(eval_res)

        eval_map: Dict[str, FeasibilityCheckResult] = {e.model_id: e for e in evaluations}

        # 2. Handle FIXED Mode
        if request.selection_mode == ModelSelectionMode.FIXED:
            if not request.preferred_model_id:
                raise ValueError("preferred_model_id is required when selection_mode is FIXED")

            fixed_candidate = candidate_map.get(request.preferred_model_id)
            if not fixed_candidate:
                raise ValueError(f"Fixed model '{request.preferred_model_id}' is not in available_candidates")

            fixed_eval = eval_map[request.preferred_model_id]
            if not fixed_eval.is_feasible:
                raise ValueError(
                    f"Fixed model '{request.preferred_model_id}' violates hard constraints: {', '.join(fixed_eval.violations)}"
                )

            u_score = self.policy_evaluator.calculate_utility_score(
                feasibility=fixed_eval,
                goal=request.task_profile.metadata.get("optimization_goal") or "balanced",
            )

            return ModelSelectionDecision(
                decision_id=str(uuid.uuid4()),
                request_id=request.request_id,
                organization_id=request.organization_id,
                selected_model_id=fixed_candidate.model_id,
                selection_mode=ModelSelectionMode.FIXED,
                was_substituted=False,
                substitution_reason=SubstitutionReason.NONE,
                original_preferred_model_id=request.preferred_model_id,
                utility_score=u_score,
                estimated_cost_usd=fixed_eval.estimated_cost_usd,
                estimated_latency_ms=fixed_eval.estimated_latency_ms,
                expected_quality=fixed_eval.expected_quality,
                expected_reliability=fixed_eval.expected_reliability,
                feasibility_evaluations=evaluations,
                explanation=f"Fixed selection enforced for model '{fixed_candidate.model_id}'.",
            )

        # 3. Handle USER_PREFERRED Mode
        if request.selection_mode == ModelSelectionMode.USER_PREFERRED and request.preferred_model_id:
            pref_candidate = candidate_map.get(request.preferred_model_id)
            pref_eval = eval_map.get(request.preferred_model_id) if pref_candidate else None

            if pref_candidate and pref_eval and pref_eval.is_feasible:
                u_score = self.policy_evaluator.calculate_utility_score(
                    feasibility=pref_eval,
                    goal=request.task_profile.metadata.get("optimization_goal") or "balanced",
                )
                return ModelSelectionDecision(
                    decision_id=str(uuid.uuid4()),
                    request_id=request.request_id,
                    organization_id=request.organization_id,
                    selected_model_id=pref_candidate.model_id,
                    selection_mode=ModelSelectionMode.USER_PREFERRED,
                    was_substituted=False,
                    substitution_reason=SubstitutionReason.NONE,
                    original_preferred_model_id=request.preferred_model_id,
                    utility_score=u_score,
                    estimated_cost_usd=pref_eval.estimated_cost_usd,
                    estimated_latency_ms=pref_eval.estimated_latency_ms,
                    expected_quality=pref_eval.expected_quality,
                    expected_reliability=pref_eval.expected_reliability,
                    feasibility_evaluations=evaluations,
                    explanation=f"User preferred model '{pref_candidate.model_id}' is feasible and selected.",
                )

        # 4. AUTOMATIC Selection or USER_PREFERRED Fallback
        feasible_pairs = [(candidate_map[e.model_id], e) for e in evaluations if e.is_feasible]

        if not feasible_pairs:
            raise ValueError(
                f"No feasible model candidate found for request {request.request_id}. "
                f"Evaluated {len(evaluations)} candidates, all violated constraints."
            )

        # Utility calculation for candidates
        scored_candidates = []
        opt_goal = request.task_profile.metadata.get("optimization_goal") or "balanced"
        max_budget_ref = request.task_profile.constraints.max_budget_usd or 0.10
        max_lat_ref = request.task_profile.constraints.max_latency_ms or 5000.0

        for cand, fe_eval in feasible_pairs:
            u_score = self.policy_evaluator.calculate_utility_score(
                feasibility=fe_eval,
                goal=opt_goal,
                max_budget_ref=max_budget_ref,
                max_latency_ref=max_lat_ref,
            )
            scored_candidates.append((cand, fe_eval, u_score))

        # Sort by Utility score descending
        scored_candidates.sort(key=lambda item: item[2], reverse=True)
        best_cand, best_eval, best_u_score = scored_candidates[0]

        was_substituted = False
        sub_reason = SubstitutionReason.NONE
        pref_cand = candidate_map.get(request.preferred_model_id) if request.preferred_model_id else None
        pref_eval = eval_map.get(request.preferred_model_id) if request.preferred_model_id else None

        if request.preferred_model_id and best_cand.model_id != request.preferred_model_id:
            was_substituted = True
            sub_reason = self.substitution_engine.determine_substitution_reason(
                preferred_eval=pref_eval,
                selected_candidate=best_cand,
                preferred_candidate=pref_cand,
            )

        explanation = (
            f"Selected model '{best_cand.model_id}' with utility score {best_u_score:.4f}. "
            f"Mode: {request.selection_mode.value}."
        )
        if was_substituted:
            explanation += f" Substituted from preferred model '{request.preferred_model_id}' due to: {sub_reason.value}."

        return ModelSelectionDecision(
            decision_id=str(uuid.uuid4()),
            request_id=request.request_id,
            organization_id=request.organization_id,
            selected_model_id=best_cand.model_id,
            selection_mode=request.selection_mode,
            was_substituted=was_substituted,
            substitution_reason=sub_reason,
            original_preferred_model_id=request.preferred_model_id,
            utility_score=best_u_score,
            estimated_cost_usd=best_eval.estimated_cost_usd,
            estimated_latency_ms=best_eval.estimated_latency_ms,
            expected_quality=best_eval.expected_quality,
            expected_reliability=best_eval.expected_reliability,
            feasibility_evaluations=evaluations,
            explanation=explanation,
        )

    def _check_feasibility(
        self,
        candidate: ModelCandidate,
        task_profile: TaskProfile,
        estimated_input_tokens: int,
        estimated_output_tokens: int,
        perf_profile: Optional[PerformanceProfile] = None,
    ) -> FeasibilityCheckResult:
        violations = []

        total_tokens = estimated_input_tokens + estimated_output_tokens
        if total_tokens > candidate.context_window_tokens:
            violations.append(
                f"Total requested tokens ({total_tokens}) exceeds candidate context window capacity ({candidate.context_window_tokens})"
            )

        if estimated_output_tokens > candidate.max_output_tokens:
            violations.append(
                f"Estimated output tokens ({estimated_output_tokens}) exceeds candidate max output limit ({candidate.max_output_tokens})"
            )

        allowed = task_profile.constraints.allowed_models
        if allowed and candidate.model_id not in allowed:
            violations.append(f"Model '{candidate.model_id}' is not in allowed models list: {allowed}")

        forbidden = task_profile.constraints.forbidden_models
        if forbidden and candidate.model_id in forbidden:
            violations.append(f"Model '{candidate.model_id}' is explicitly forbidden")

        if task_profile.classification.primary_domain.value == "multimodal" or "vision" in task_profile.metadata:
            if not candidate.supports_vision:
                violations.append("Task requires vision support, but model does not support vision")

        req_tools = task_profile.constraints.required_tools
        if req_tools and not candidate.supports_function_calling:
            violations.append("Task requires tool/function calling, but model does not support function calling")

        est_cost = self.policy_evaluator.compute_estimated_cost(
            candidate=candidate,
            input_tokens=estimated_input_tokens,
            output_tokens=estimated_output_tokens,
        )

        max_budget = task_profile.constraints.max_budget_usd
        if max_budget is not None and est_cost > max_budget:
            violations.append(f"Estimated cost ${est_cost:.6f} exceeds maximum task budget ${max_budget:.6f}")

        if perf_profile:
            est_latency = perf_profile.metrics.latency_p50_ms
            exp_quality = perf_profile.metrics.quality_mean
            exp_reliability = perf_profile.metrics.reliability_rate
        else:
            est_latency = candidate.typical_latency_ms
            exp_quality = 0.80 if candidate.tier == "flagship" else 0.70
            exp_reliability = 0.90

        max_latency = task_profile.constraints.max_latency_ms
        if max_latency is not None and est_latency > max_latency:
            violations.append(f"Estimated latency {est_latency:.1f}ms exceeds maximum latency threshold {max_latency:.1f}ms")

        min_quality = task_profile.constraints.min_quality_score
        if min_quality is not None and exp_quality < min_quality:
            violations.append(f"Expected quality {exp_quality:.2f} is below required threshold {min_quality:.2f}")

        min_rel = task_profile.constraints.min_reliability_score
        if min_rel is not None and exp_reliability < min_rel:
            violations.append(f"Expected reliability {exp_reliability:.2f} is below required threshold {min_rel:.2f}")

        return FeasibilityCheckResult(
            model_id=candidate.model_id,
            is_feasible=len(violations) == 0,
            violations=violations,
            estimated_cost_usd=est_cost,
            estimated_latency_ms=est_latency,
            expected_quality=exp_quality,
            expected_reliability=exp_reliability,
        )
