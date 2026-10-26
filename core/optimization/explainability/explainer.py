"""
Decision Explainer Service for C11 Optimization System.
"""

import logging
from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from core.storage.models.optimization_c11_governance import (
    OptimizationDecisionModel,
    OptimizationPolicyModel,
    OptimizationSnapshotModel,
)
from schemas.domain.governance import DecisionType, OptimizationDecision
from schemas.domain.observability import DecisionChainExplanation

logger = logging.getLogger(__name__)

class DecisionExplainer:
    def __init__(self, db: Session):
        self.db = db

    def explain_request(self, request_id: str, tenant_id: str) -> Optional[DecisionChainExplanation]:
        snapshot_model = (
            self.db.query(OptimizationSnapshotModel)
            .filter(
                OptimizationSnapshotModel.optimization_id == request_id,
                OptimizationSnapshotModel.organization_id == tenant_id,
            )
            .first()
        )

        decision_models = (
            self.db.query(OptimizationDecisionModel)
            .filter(
                OptimizationDecisionModel.optimization_id == request_id,
                OptimizationDecisionModel.organization_id == tenant_id,
            )
            .order_by(OptimizationDecisionModel.created_at.asc())
            .all()
        )

        if not snapshot_model and not decision_models:
            return None

        decisions: List[OptimizationDecision] = []
        for dm in decision_models:
            decisions.append(
                OptimizationDecision(
                    decision_id=dm.decision_id,
                    optimization_id=dm.optimization_id,
                    task_id=dm.task_id,
                    organization_id=dm.organization_id,
                    decision_type=dm.decision_type,
                    chosen_option=dm.chosen_option,
                    rejected_options=dm.rejected_options or [],
                    decision_reasons=dm.decision_reasons or [],
                    policy_id=dm.policy_id,
                    confidence_score=dm.confidence_score,
                    evidence_references=dm.evidence_references or [],
                    created_at=dm.created_at,
                )
            )

        model_reasoning = "Model selected based on task intelligence and policy compliance."
        strategy_reasoning = "Strategies chosen via multi-armed bandit performance evaluation."
        verification_reasoning = "Verification pipeline configured with safety checks."
        fallback_active = False

        for d in decisions:
            if d.decision_type == DecisionType.MODEL_SELECTION:
                reasons_str = " ".join(d.decision_reasons)
                model_reasoning = f"Model selected: {reasons_str}"
            elif d.decision_type == DecisionType.STRATEGY_SELECTION:
                strategy_reasoning = " ".join(d.decision_reasons)

        plan_data = snapshot_model.verification_plan_json if snapshot_model else {}
        cost_usd = snapshot_model.estimated_cost if snapshot_model else 0.0
        latency_ms = snapshot_model.estimated_latency_ms if snapshot_model else 0.0

        cost_breakdown = {
            "model_cost_usd": cost_usd * 0.8,
            "verification_cost_usd": cost_usd * 0.2,
            "total_cost_usd": cost_usd,
        }

        latency_breakdown = {
            "model_latency_ms": latency_ms * 0.7,
            "verification_duration_ms": latency_ms * 0.3,
            "total_latency_ms": latency_ms,
        }

        return DecisionChainExplanation(
            request_id=request_id,
            plan_id=snapshot_model.snapshot_id if snapshot_model else f"plan_{request_id[:8]}",
            tenant_id=tenant_id,
            decisions=decisions,
            model_selection_reasoning=model_reasoning,
            strategy_selection_reasoning=strategy_reasoning,
            verification_pruning_reasoning=verification_reasoning,
            governance_policy_applied="DEFAULT",
            fallback_active=fallback_active,
            cost_breakdown_usd=cost_breakdown,
            latency_breakdown_ms=latency_breakdown,
            risk_assessment={"risk_score": 0.1, "is_pruned": False},
        )
