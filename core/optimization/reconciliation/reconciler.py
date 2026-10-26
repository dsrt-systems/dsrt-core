"""
Performance Reconciliation Engine for C11 Optimization System.
"""

import logging
import uuid
from typing import Optional
from sqlalchemy.orm import Session

from core.optimization.events.publisher import OptimizationEventPublisher, ReconciliationCompletedEvent
from core.optimization.profiles.agent_strategy_profiles import AgentPerformanceRegistry
from core.storage.models.optimization_c11_governance import OptimizationSnapshotModel
from core.storage.models.optimization_c11_observability import ReconciliationReportModel
from schemas.domain.observability import ExecutionActuals, ReconciliationReport

logger = logging.getLogger(__name__)

class PerformanceReconciler:
    def __init__(self, db: Session, event_publisher: Optional[OptimizationEventPublisher] = None):
        self.db = db
        self.agent_registry = AgentPerformanceRegistry(db)
        self.event_publisher = event_publisher or OptimizationEventPublisher()

    def reconcile(self, actuals: ExecutionActuals) -> ReconciliationReport:
        snapshot = (
            self.db.query(OptimizationSnapshotModel)
            .filter(
                OptimizationSnapshotModel.optimization_id == actuals.request_id,
                OptimizationSnapshotModel.organization_id == actuals.tenant_id,
            )
            .first()
        )

        pred_cost = snapshot.estimated_cost if snapshot else 0.05
        pred_lat = snapshot.estimated_latency_ms if snapshot else 1500.0
        pred_qual = snapshot.estimated_quality if snapshot else 0.85
        plan_id = snapshot.snapshot_id if snapshot else f"plan_{actuals.request_id[:8]}"

        cost_err_pct = ((actuals.actual_cost_usd - pred_cost) / pred_cost * 100.0) if pred_cost > 0 else 0.0
        lat_err_pct = ((actuals.actual_latency_ms - pred_lat) / pred_lat * 100.0) if pred_lat > 0 else 0.0
        qual_err_pct = ((actuals.actual_quality_score - pred_qual) / pred_qual * 100.0) if pred_qual > 0 else 0.0

        recon_id = str(uuid.uuid4())
        recon_model = ReconciliationReportModel(
            id=recon_id,
            request_id=actuals.request_id,
            plan_id=plan_id,
            organization_id=actuals.tenant_id,
            predicted_cost_usd=pred_cost,
            actual_cost_usd=actuals.actual_cost_usd,
            cost_error_pct=round(cost_err_pct, 2),
            predicted_latency_ms=pred_lat,
            actual_latency_ms=actuals.actual_latency_ms,
            latency_error_pct=round(lat_err_pct, 2),
            predicted_quality_score=pred_qual,
            actual_quality_score=actuals.actual_quality_score,
            quality_error_pct=round(qual_err_pct, 2),
        )

        self.db.add(recon_model)
        self.db.commit()

        report = ReconciliationReport(
            id=recon_id,
            request_id=actuals.request_id,
            plan_id=plan_id,
            tenant_id=actuals.tenant_id,
            predicted_cost_usd=pred_cost,
            actual_cost_usd=actuals.actual_cost_usd,
            cost_error_pct=round(cost_err_pct, 2),
            predicted_latency_ms=pred_lat,
            actual_latency_ms=actuals.actual_latency_ms,
            latency_error_pct=round(lat_err_pct, 2),
            predicted_quality_score=pred_qual,
            actual_quality_score=actuals.actual_quality_score,
            quality_error_pct=round(qual_err_pct, 2),
        )
        return report
