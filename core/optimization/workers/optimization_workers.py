"""
Asynchronous Background Workers for C11 Optimization System.
"""

import logging
from typing import Dict, Any
from sqlalchemy.orm import Session

from core.optimization.performance_registry.registry import PerformanceIntelligenceRegistry
from core.optimization.strategy_learning.engine import StrategyLearningEngine

logger = logging.getLogger(__name__)


class OptimizationWorkerManager:
    def __init__(self, db: Session):
        self.db = db
        self.registry = PerformanceIntelligenceRegistry(db=db)
        self.learning_engine = StrategyLearningEngine(db)

    def run_profile_aggregation_worker(self) -> Dict[str, Any]:
        logger.info("Executing Profile Aggregation Worker...")
        models = ["claude-3-5-sonnet", "gpt-4o", "gpt-4o-mini"]
        updated = 0
        for model_id in models:
            try:
                prof = self.registry.get_model_profile(model_id, "coding")
                if prof:
                    updated += 1
            except Exception:
                pass
        return {"status": "success", "models_aggregated": updated}

    def run_learning_worker(self) -> Dict[str, Any]:
        logger.info("Executing Strategy Learning Worker...")
        try:
            metrics = self.learning_engine.get_metrics()
            total_arms = getattr(metrics, "total_arms", 0)
            active = getattr(metrics, "active_experiments", 0)
        except Exception:
            total_arms = 0
            active = 0
        return {"status": "success", "total_arms": total_arms, "active_experiments": active}
