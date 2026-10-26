"""
Master Optimization Controller for C11.9.
Coordinates all C11 sub-modules with sync/async compatibility.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from schemas.domain.governance import (
    OptimizationRequest,
    OptimizationPlanV2,
    OptimizationPolicy,
    OptimizationDecision,
    OptimizationSnapshot,
    PolicyCheckResult,
    DecisionType,
    FallbackMode,
)
from core.optimization.policy.enforcer import PolicyEnforcer
from core.optimization.fallback.circuit_breaker import FallbackCircuitBreaker
from core.storage.models.optimization_c11_governance import (
    OptimizationDecisionModel,
    OptimizationSnapshotModel,
)


class MasterOptimizationController:
    """Central facade coordinating all C11 optimization decisions."""

    def __init__(
        self,
        db_session=None,
        policy_enforcer: Optional[PolicyEnforcer] = None,
        circuit_breaker: Optional[FallbackCircuitBreaker] = None,
    ):
        self.db_session = db_session
        self.policy_enforcer = policy_enforcer or PolicyEnforcer(db_session=db_session)
        self.circuit_breaker = circuit_breaker or FallbackCircuitBreaker(db_session=db_session)

    def optimize(self, request: OptimizationRequest) -> OptimizationPlanV2:
        """Full optimization workflow (sync-compatible)."""
        if self.circuit_breaker.should_use_fallback():
            fallback_data = self.circuit_breaker.get_fallback_plan(
                request_task_id=request.task_id
            )
            return self._build_fallback_plan(request, fallback_data)

        try:
            policy = self.policy_enforcer.get_active_policy(
                organization_id=request.organization_id,
                user_id=getattr(request, "user_id", None),
            )
            if policy is None:
                policy = self.policy_enforcer.create_default_policy(
                    organization_id=request.organization_id,
                    user_id=getattr(request, "user_id", None),
                )

            compliance = self.policy_enforcer.check_request_compliance(request, policy)

            if compliance.blocking:
                message = "Policy violation blocks execution"
                if compliance.violations:
                    message = f"Policy violation: {compliance.violations[0].message}"
                self.circuit_breaker.record_failure(message)
                return self._build_rejected_plan(request, policy, compliance)

            plan = self._build_optimization_plan(request, policy, compliance)
            self._record_decisions(request, plan, policy)
            snapshot = self._create_snapshot(request, plan, policy)
            plan.snapshot_id = snapshot.snapshot_id
            self.circuit_breaker.record_success()
            return plan

        except Exception as e:
            self.circuit_breaker.record_failure(f"Optimization failed: {str(e)[:200]}")
            fallback_data = self.circuit_breaker.get_fallback_plan(
                request_task_id=request.task_id
            )
            return self._build_fallback_plan(request, fallback_data)

    def optimize_task(self, request: OptimizationRequest) -> OptimizationPlanV2:
        """Alias for optimize (used by C9 adapter)."""
        return self.optimize(request)

    def _build_optimization_plan(self, request, policy, compliance):
        selected_model_id = self._select_compliant_model(request, policy)
        selected_agent = getattr(request, "agent_preference", None) or (
            policy.preferred_agents[0] if policy.preferred_agents else None
        )
        selected_strategies = self._select_strategies(request, policy)
        verification_plan = self._build_verification_plan(request, policy)
        estimated_cost = self._estimate_cost(selected_model_id, selected_strategies, verification_plan)
        estimated_latency = self._estimate_latency(selected_model_id, selected_strategies, verification_plan)

        decision_reasons = [
            f"Policy-compliant model selected: {selected_model_id}",
            f"Optimization mode: {policy.optimization_mode}",
            f"Enforcement level: {policy.enforcement_level.value if hasattr(policy.enforcement_level, 'value') else policy.enforcement_level}",
        ]
        if compliance.approval_required:
            decision_reasons.append("Approval required due to policy constraints")

        return OptimizationPlanV2(
            optimization_id=request.request_id,
            plan_version=1,
            task_profile_id=f"profile-{request.task_id}",
            organization_id=request.organization_id,
            selected_model={"model_id": selected_model_id, "selection_mode": policy.model_selection_lock},
            selected_agent={"agent_id": selected_agent} if selected_agent else None,
            selected_strategies=[{"strategy_id": s} for s in selected_strategies],
            verification_plan=verification_plan,
            estimated_quality=policy.min_quality_score + 0.10,
            estimated_reliability=policy.min_reliability_score + 0.05,
            estimated_cost=estimated_cost,
            estimated_latency_ms=estimated_latency,
            authorized_budget=getattr(request, "max_cost", None) or policy.max_cost_usd_per_task,
            decision_reasons=decision_reasons,
            limitations=[v.message for v in compliance.violations if getattr(v, "severity", "") == "warning"],
            policy_compliance={"policy_id": policy.policy_id, "is_compliant": compliance.is_compliant, "violation_count": len(compliance.violations)},
            approval_required=compliance.approval_required,
            status="draft" if compliance.approval_required else "ready",
            fallback_mode=FallbackMode.HEALTHY,
        )

    def _select_compliant_model(self, request, policy):
        if policy.model_selection_lock == "fixed" and policy.preferred_models:
            return policy.preferred_models[0]
        pref = getattr(request, "model_preference", "automatic")
        if pref and pref != "automatic":
            check = self.policy_enforcer.check_model_selection_compliance(pref, policy)
            if getattr(check, "is_compliant", True):
                return pref
        if policy.preferred_models:
            return policy.preferred_models[0]
        if policy.allowed_models:
            return policy.allowed_models[0]
        return "default_reliable_model"

    def _select_strategies(self, request, policy):
        if policy.optimization_mode == "economy":
            return ["basic_execution"]
        if policy.optimization_mode == "quality":
            return ["context_retrieval", "evidence_grounding", "verification", "structured_planning"]
        return ["context_retrieval", "structured_planning"]

    def _build_verification_plan(self, request, policy):
        strategy_type = "balanced"
        required_checks = ["syntax_lint", "unit_test"]
        if policy.require_mandatory_security_checks:
            required_checks.append("security_scan")
        if policy.optimization_mode == "quality":
            strategy_type = "thorough"
            required_checks.extend(["static_analysis", "integration_test"])
        elif policy.optimization_mode == "economy":
            strategy_type = "minimal"
        return {
            "strategy_type": strategy_type,
            "required_checks": required_checks,
            "security_checks_included": policy.require_mandatory_security_checks,
            "mandatory_security_enforced": policy.require_mandatory_security_checks,
        }

    def _estimate_cost(self, model_id, strategies, verification_plan):
        base = 0.02
        strat = len(strategies) * 0.01
        verif = len(verification_plan.get("required_checks", [])) * 0.015
        return round(base + strat + verif + 0.005 + (0.01 if "context_retrieval" in strategies else 0.0) + 0.01, 6)

    def _estimate_latency(self, model_id, strategies, verification_plan):
        return round(1500.0 + len(strategies) * 300.0 + len(verification_plan.get("required_checks", [])) * 500.0, 2)

    def _record_decisions(self, request, plan, policy):
        if self.db_session is None:
            return
        decisions = [
            OptimizationDecisionModel(
                decision_id=str(uuid.uuid4()),
                optimization_id=request.request_id,
                task_id=request.task_id,
                organization_id=request.organization_id,
                decision_type=DecisionType.MODEL_SELECTION.value,
                decision_subject="model",
                chosen_option=plan.selected_model.get("model_id", "unknown"),
                rejected_options=[],
                decision_reasons=plan.decision_reasons,
                evidence_references=[],
                policy_id=policy.policy_id,
                confidence_score=1.0,
            ),
        ]
        for strat in plan.selected_strategies:
            decisions.append(
                OptimizationDecisionModel(
                    decision_id=str(uuid.uuid4()),
                    optimization_id=request.request_id,
                    task_id=request.task_id,
                    organization_id=request.organization_id,
                    decision_type=DecisionType.STRATEGY_SELECTION.value,
                    decision_subject="strategy",
                    chosen_option=strat.get("strategy_id", "unknown"),
                    rejected_options=[],
                    decision_reasons=plan.decision_reasons,
                    evidence_references=[],
                    policy_id=policy.policy_id,
                    confidence_score=1.0,
                )
            )
        for d in decisions:
            self.db_session.add(d)
        try:
            self.db_session.commit()
        except Exception:
            self.db_session.rollback()

    def _create_snapshot(self, request, plan, policy):
        snapshot = OptimizationSnapshot(
            optimization_id=request.request_id,
            task_id=request.task_id,
            organization_id=request.organization_id,
            plan_version=plan.plan_version,
            task_profile_json={"task_id": request.task_id, "description": request.task_description},
            selected_model=plan.selected_model.get("model_id", "unknown"),
            selected_agent=(plan.selected_agent or {}).get("agent_id"),
            selected_strategies=[s.get("strategy_id", "unknown") for s in plan.selected_strategies],
            verification_plan_json=plan.verification_plan,
            policy_snapshot_json=policy.model_dump(mode="json"),
            estimated_cost=plan.estimated_cost,
            estimated_latency_ms=plan.estimated_latency_ms,
            estimated_quality=plan.estimated_quality,
        )
        if self.db_session is not None:
            db_m = OptimizationSnapshotModel(
                snapshot_id=snapshot.snapshot_id,
                optimization_id=snapshot.optimization_id,
                task_id=snapshot.task_id,
                organization_id=snapshot.organization_id,
                plan_version=snapshot.plan_version,
                task_profile_json=snapshot.task_profile_json,
                selected_model=snapshot.selected_model,
                selected_agent=snapshot.selected_agent,
                selected_strategies=snapshot.selected_strategies,
                verification_plan_json=snapshot.verification_plan_json,
                policy_snapshot_json=snapshot.policy_snapshot_json,
                evidence_snapshot_json=snapshot.evidence_snapshot_json,
                estimated_cost=snapshot.estimated_cost,
                estimated_latency_ms=snapshot.estimated_latency_ms,
                estimated_quality=snapshot.estimated_quality,
            )
            self.db_session.add(db_m)
            try:
                self.db_session.commit()
            except Exception:
                self.db_session.rollback()
        return snapshot

    def _build_fallback_plan(self, request, fallback_data):
        return OptimizationPlanV2(
            optimization_id=request.request_id,
            plan_version=1,
            task_profile_id=f"profile-{request.task_id}",
            organization_id=request.organization_id,
            selected_model={"model_id": fallback_data.get("selected_model", "default")},
            selected_strategies=[{"strategy_id": s} for s in fallback_data.get("selected_strategies", [])],
            verification_plan=fallback_data.get("verification_plan", {}),
            estimated_quality=fallback_data.get("estimated_quality", 0.85),
            estimated_reliability=0.70,
            estimated_cost=fallback_data.get("estimated_cost", 0.06),
            estimated_latency_ms=fallback_data.get("estimated_latency_ms", 6200.0),
            decision_reasons=[fallback_data.get("fallback_reason", "fallback"), fallback_data.get("warning", "")],
            status="fallback",
            fallback_mode=self.circuit_breaker.get_state().mode,
        )

    def _build_rejected_plan(self, request, policy, compliance):
        return OptimizationPlanV2(
            optimization_id=request.request_id,
            plan_version=1,
            task_profile_id=f"profile-{request.task_id}",
            organization_id=request.organization_id,
            selected_model={"model_id": "none"},
            selected_strategies=[],
            verification_plan={},
            estimated_quality=0.0,
            estimated_reliability=0.0,
            estimated_cost=0.0,
            estimated_latency_ms=0.0,
            decision_reasons=["Policy violation blocks execution"],
            limitations=[v.message for v in compliance.violations],
            policy_compliance={"policy_id": policy.policy_id, "is_compliant": False, "violation_count": len(compliance.violations)},
            status="rejected",
            fallback_mode=FallbackMode.HEALTHY,
        )
