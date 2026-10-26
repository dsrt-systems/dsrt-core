"""
Phase C11.2: Performance Evidence Collector & Aggregator

Records granular execution outcomes from traces and evaluates historical performance data.
"""

import math
import uuid
from typing import List, Optional
from sqlalchemy.orm import Session

from schemas.domain.performance_intelligence import (
    PerformanceEvidence,
    PerformanceMetrics,
)
from core.storage.models.optimization_c11 import PerformanceEvidenceModel


class PerformanceEvidenceCollector:
    """Collects and aggregates granular execution evidence."""

    def record_evidence(
        self,
        evidence: PerformanceEvidence,
        session: Optional[Session] = None,
    ) -> PerformanceEvidence:
        if session is not None:
            db_model = PerformanceEvidenceModel(
                id=evidence.evidence_id,
                model_id=evidence.model_id,
                organization_id=evidence.organization_id,
                domain=evidence.domain,
                intent=evidence.intent,
                complexity_level=evidence.complexity_level,
                quality_score=evidence.quality_score,
                reliability_score=evidence.reliability_score,
                latency_ms=evidence.latency_ms,
                total_tokens=evidence.input_tokens + evidence.output_tokens,
                cost_usd=evidence.cost_usd,
                error_type=evidence.error_type,
                created_at=evidence.timestamp,
            )
            db_model.set_evidence_data(evidence.model_dump(mode="json"))
            session.add(db_model)
            session.commit()

        return evidence

    def fetch_evidence(
        self,
        model_id: str,
        organization_id: str,
        domain: Optional[str] = None,
        intent: Optional[str] = None,
        complexity_level: Optional[str] = None,
        session: Optional[Session] = None,
    ) -> List[PerformanceEvidence]:
        if session is None:
            return []

        query = session.query(PerformanceEvidenceModel).filter(
            PerformanceEvidenceModel.model_id == model_id,
            PerformanceEvidenceModel.organization_id == organization_id,
        )

        if domain and domain != "all":
            query = query.filter(PerformanceEvidenceModel.domain == domain)
        if intent and intent != "all":
            query = query.filter(PerformanceEvidenceModel.intent == intent)
        if complexity_level and complexity_level != "all":
            query = query.filter(PerformanceEvidenceModel.complexity_level == complexity_level)

        db_models = query.order_by(PerformanceEvidenceModel.created_at.desc()).all()

        results = []
        for row in db_models:
            data = row.get_evidence_data()
            if data:
                results.append(PerformanceEvidence(**data))
            else:
                results.append(
                    PerformanceEvidence(
                        evidence_id=row.id,
                        model_id=row.model_id,
                        organization_id=row.organization_id,
                        domain=row.domain,
                        intent=row.intent,
                        complexity_level=row.complexity_level,
                        quality_score=row.quality_score,
                        reliability_score=row.reliability_score,
                        latency_ms=row.latency_ms,
                        input_tokens=0,
                        output_tokens=row.total_tokens,
                        cost_usd=row.cost_usd,
                        error_type=row.error_type,
                        timestamp=row.created_at,
                    )
                )

        return results