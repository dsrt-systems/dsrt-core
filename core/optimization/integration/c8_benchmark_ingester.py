"""
C8 Benchmark Ingestion Adapter for Phase C11.
Ingests historical benchmark execution telemetry from C8 into C11 Performance Intelligence Registry.
"""

import logging
import uuid
from typing import Any, Dict, List
from sqlalchemy.orm import Session

from core.optimization.performance_registry.registry import PerformanceIntelligenceRegistry
from schemas.domain.performance_intelligence import PerformanceEvidence

logger = logging.getLogger(__name__)


class C8BenchmarkIngester:
    """
    Processes benchmark evaluation logs from Phase C8 and populates C11 performance evidence.
    """

    def __init__(self, db: Session):
        self.db = db
        self.registry = PerformanceIntelligenceRegistry(db=db)

    def ingest_benchmark_results(self, benchmark_records: List[Dict[str, Any]]) -> int:
        """
        Parses raw C8 benchmark runs and records evidence into C11 Bayesian performance profiles.
        """
        ingested_count = 0
        for rec in benchmark_records:
            evidence = PerformanceEvidence(
                evidence_id=rec.get("evidence_id", str(uuid.uuid4())),
                model_id=rec.get("model_id", "gpt-4o"),
                organization_id=rec.get("organization_id", rec.get("tenant_id", "c8_benchmark")),
                domain=rec.get("task_classification", "coding"),
                intent=rec.get("intent", "code_generation"),
                complexity_level=rec.get("complexity_level", "medium"),
                quality_score=rec.get("quality_score", 0.90),
                reliability_score=1.0 if rec.get("is_success", True) else 0.0,
                latency_ms=rec.get("latency_ms", 1500.0),
                input_tokens=rec.get("input_tokens", 0),
                output_tokens=rec.get("output_tokens", 0),
                cost_usd=rec.get("cost_usd", 0.02),
                error_type=rec.get("error_type"),
                error_message=rec.get("error_message"),
            )
            self.registry.ingest_evidence(evidence, session=self.db)
            ingested_count += 1

        logger.info(f"Successfully ingested {ingested_count} C8 benchmark evidence records into C11 registry.")
        return ingested_count
