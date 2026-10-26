"""
C9 Execution Adapter for Phase C11.
Bridges C9 routing decisions into C11 optimization pipeline.
"""

import logging
from typing import Any, Dict

from core.optimization.controller.master_controller import MasterOptimizationController
from schemas.domain.governance import OptimizationRequest

logger = logging.getLogger(__name__)


class C9ExecutionAdapter:
    """Adapts C9 routing output into C11 optimization directives."""

    def __init__(self, db=None):
        self.db = db
        self.controller = MasterOptimizationController(db_session=db)

    def prepare_execution_directives(self, c9_request: Dict[str, Any]) -> Dict[str, Any]:
        """Converts a C9 routing request into C11-optimized execution directives."""
        request_id = c9_request.get("request_id", "unknown")
        task_id = f"task_{request_id}"

        opt_request = OptimizationRequest(
            request_id=request_id,
            organization_id=c9_request.get("tenant_id", "default-org"),
            task_id=task_id,
            task_description=c9_request.get("prompt", ""),
            max_cost=c9_request.get("max_cost_usd", 0.10),
        )

        plan = self.controller.optimize(opt_request)

        model_id = plan.selected_model.get("model_id", "gpt-4o-mini")
        if model_id not in ["claude-3-5-sonnet", "gpt-4o", "gpt-4o-mini"]:
            model_id = "gpt-4o-mini"

        return {
            "task_id": task_id,
            "selected_model": model_id,
            "verification_pipeline": plan.verification_plan,
            "estimated_cost": plan.estimated_cost,
            "estimated_latency_ms": plan.estimated_latency_ms,
            "strategies": plan.selected_strategies,
        }
