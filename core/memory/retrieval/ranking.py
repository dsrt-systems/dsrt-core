"""
Hybrid Memory Ranker (C4 §17).

Merges candidates from multiple retrieval strategies (vector, keyword, temporal)
and ranks them deterministically using a multi-factor scoring function.
"""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any

from schemas.domain.enums import MemoryImportance, MemoryScope, MemoryVerificationState
from schemas.domain.memory import Memory, MemoryRetrievalResult


@dataclass(frozen=True)
class RankingWeights:
    """Configurable weights for the hybrid ranking formula."""
    semantic_similarity: float = 0.40
    keyword_match: float = 0.20
    temporal_recency: float = 0.10
    importance: float = 0.10
    scope_relevance: float = 0.10
    verification_status: float = 0.10


class HybridRanker:
    """Deterministically ranks memory candidates."""

    def __init__(self, weights: RankingWeights | None = None) -> None:
        self.weights = weights or RankingWeights()
        self._now = datetime.now(timezone.utc)

    def rank_and_merge(
        self,
        vector_candidates: list[dict[str, Any]],
        keyword_candidates: list[Memory],
        temporal_candidates: list[Memory],
        target_scope: MemoryScope,
        limit: int,
    ) -> list[MemoryRetrievalResult]:
        """Merge candidates, calculate hybrid scores, deduplicate, and sort."""
        
        merged: dict[str, MemoryRetrievalResult] = {}

        # 1. Process Vector Candidates
        for cand in vector_candidates:
            mem_id = cand["memory_id"]
            # Convert raw dict back to Memory object structure for scoring (mocked for simplicity here)
            # In practice, the engine passes the full Memory object or we fetch it.
            # We assume vector_candidates already have 'similarity' populated.
            sim_score = cand.get("similarity", 0.0)
            
            if mem_id not in merged:
                merged[mem_id] = self._init_result(cand["memory_obj"], "vector", sim_score)
            else:
                merged[mem_id].retrieval_method = "hybrid"
                merged[mem_id].provenance["vector_score"] = sim_score

        # 2. Process Keyword Candidates
        for mem in keyword_candidates:
            if mem.id not in merged:
                merged[mem.id] = self._init_result(mem, "keyword", 0.0)
                merged[mem.id].provenance["keyword_match"] = 1.0
            else:
                merged[mem.id].retrieval_method = "hybrid"
                merged[mem.id].provenance["keyword_match"] = 1.0

        # 3. Process Temporal Candidates
        for mem in temporal_candidates:
            if mem.id not in merged:
                merged[mem.id] = self._init_result(mem, "temporal", 0.0)
            else:
                merged[mem.id].retrieval_method = "hybrid"

        # 4. Calculate Final Hybrid Scores
        for mem_id, result in merged.items():
            result.relevance_score = self._compute_score(result, target_scope)

        # 5. Sort and Limit
        sorted_results = sorted(merged.values(), key=lambda x: x.relevance_score, reverse=True)
        return sorted_results[:limit]

    def _init_result(self, memory: Memory, method: str, sim_score: float) -> MemoryRetrievalResult:
        return MemoryRetrievalResult(
            memory=memory,
            relevance_score=0.0,  # Computed later
            retrieval_method=method,
            provenance={"vector_score": sim_score},
        )

    def _compute_score(self, result: MemoryRetrievalResult, target_scope: MemoryScope) -> float:
        """Compute the weighted hybrid score for a memory."""
        mem = result.memory
        prov = result.provenance

        # Semantic Base Score (0.0 - 1.0)
        semantic = max(0.0, prov.get("vector_score", 0.0))

        # Keyword Boost (0.0 or 1.0)
        lexical = prov.get("keyword_match", 0.0)

        # Temporal Decay (0.0 - 1.0) - Newer is better
        temporal = self._calculate_recency(mem.observed_at or mem.created_at)

        # Importance (0.0 - 1.0)
        importance_map = {
            MemoryImportance.TRIVIAL: 0.1,
            MemoryImportance.NORMAL: 0.5,
            MemoryImportance.IMPORTANT: 0.8,
            MemoryImportance.CRITICAL: 1.0,
        }
        importance = importance_map.get(mem.importance, 0.5)

        # Scope Relevance (0.0 - 1.0) - Exact scope match is best
        scope_score = 1.0 if mem.scope_type == target_scope else 0.5

        # Verification Status (0.0 - 1.0)
        verify_map = {
            MemoryVerificationState.UNVERIFIED: 0.5,
            MemoryVerificationState.VERIFIED: 1.0,
            MemoryVerificationState.DISPUTED: 0.2,
            MemoryVerificationState.CONTRADICTED: 0.0,
        }
        verification = verify_map.get(mem.verification_state, 0.5)

        # Calculate weighted sum
        w = self.weights
        total_score = (
            (semantic * w.semantic_similarity) +
            (lexical * w.keyword_match) +
            (temporal * w.temporal_recency) +
            (importance * w.importance) +
            (scope_score * w.scope_relevance) +
            (verification * w.verification_status)
        )

        return min(max(total_score, 0.0), 1.0)

    def _calculate_recency(self, dt: datetime) -> float:
        """Calculate a recency score (1.0 for now, decaying towards 0.1 for very old)."""
        delta = (self._now - dt).total_seconds()
        days_old = delta / 86400.0
        if days_old <= 0:
            return 1.0
        # Half-life of 30 days
        decay = 0.5 ** (days_old / 30.0)
        return max(0.1, decay)