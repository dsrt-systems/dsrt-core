"""
Hybrid Retrieval Engine (C4 §12, §45).

Orchestrates vector, keyword, and temporal queries against the repositories,
then ranks and merges the results.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from schemas.domain.memory import (
    Memory,
    MemoryQuery,
    MemoryRetrievalResponse,
)

from core.observability.logging import get_logger
from core.repositories.memory_repository import MemoryRepository
from core.memory.embeddings.store import EmbeddingStore
from core.memory.retrieval.ranking import HybridRanker


logger = get_logger("dsrt.memory.retrieval")


class HybridRetrievalEngine:
    """Executes multi-strategy memory retrieval and ranking."""

    def __init__(
        self,
        memory_repo: MemoryRepository,
        embedding_store: EmbeddingStore,
        ranker: HybridRanker | None = None,
    ) -> None:
        self._repo = memory_repo
        self._embeddings = embedding_store
        self._ranker = ranker or HybridRanker()

    async def search(
        self,
        organization_id: str,
        query: MemoryQuery,
    ) -> MemoryRetrievalResponse:
        """Execute a hybrid search across the memory store."""
        start_time = time.perf_counter()

        logger.debug(
            "hybrid_search_started",
            query=query.query,
            scope=query.scope.value,
        )

        fetch_limit = query.limit * 3

        # 1. Execute sub-queries concurrently (min_similarity=-1.0 to let ranker evaluate all candidates)
        vector_task = asyncio.create_task(
            self._embeddings.search_similar(
                query.query,
                organization_id=organization_id,
                scope_type=query.scope.value,
                scope_id=query.scope_id,
                memory_type=query.memory_types[0].value if query.memory_types and len(query.memory_types) == 1 else None,
                limit=fetch_limit,
                min_similarity=-1.0,
            )
        )

        keyword_task = asyncio.create_task(
            self._repo.search_content(
                organization_id=organization_id,
                query=query.query,
                scope_type=query.scope.value,
                scope_id=query.scope_id,
                memory_type=query.memory_types[0].value if query.memory_types and len(query.memory_types) == 1 else None,
                limit=fetch_limit,
            )
        )

        temporal_task = None
        if query.valid_at:
            temporal_task = asyncio.create_task(
                self._repo.search_temporal(
                    organization_id=organization_id,
                    valid_at=query.valid_at,
                    scope_type=query.scope.value,
                    scope_id=query.scope_id,
                    limit=fetch_limit,
                )
            )

        await asyncio.wait(
            [t for t in [vector_task, keyword_task, temporal_task] if t is not None]
        )

        vector_results_raw = vector_task.result() if not vector_task.exception() else []
        keyword_results_orm = keyword_task.result() if not keyword_task.exception() else []
        temporal_results_orm = temporal_task.result() if (temporal_task and not temporal_task.exception()) else []

        # 2. Hydrate vector results into Memory schemas
        vector_candidates = []
        for raw in vector_results_raw:
            mem_obj = Memory(
                id=raw["memory_id"],
                organization_id=organization_id,
                scope_type=raw["scope_type"],
                scope_id=raw["scope_id"],
                memory_type=raw["memory_type"],
                content=raw["content"],
                status=raw["status"],
                importance=raw["importance"],
                verification_state="UNVERIFIED",
                created_at=raw["created_at"],
                updated_at=raw["created_at"],
            )
            vector_candidates.append({
                "memory_id": mem_obj.id,
                "similarity": raw["similarity"],
                "memory_obj": mem_obj,
            })

        keyword_candidates = [self._to_schema(m) for m in keyword_results_orm]
        temporal_candidates = [self._to_schema(m) for m in temporal_results_orm]

        # 3. Rank and Merge
        final_results = self._ranker.rank_and_merge(
            vector_candidates=vector_candidates,
            keyword_candidates=keyword_candidates,
            temporal_candidates=temporal_candidates,
            target_scope=query.scope,
            limit=query.limit,
        )

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        logger.info(
            "hybrid_search_completed",
            results_found=len(final_results),
            duration_ms=duration_ms,
        )

        return MemoryRetrievalResponse(
            results=final_results,
            total_candidates=len(final_results),
            query=query.query,
            scope=query.scope,
            retrieval_time_ms=duration_ms,
        )

    def _to_schema(self, orm: Any) -> Memory:
        return Memory(
            id=orm.id,
            organization_id=orm.organization_id,
            scope_type=orm.scope_type,
            scope_id=orm.scope_id,
            memory_type=orm.memory_type,
            content=orm.content,
            structured_data=orm.structured_data,
            status=orm.status,
            importance=orm.importance,
            confidence=orm.confidence,
            verification_state=orm.verification_state,
            source_type=orm.source_type,
            source_id=orm.source_id,
            observed_at=orm.observed_at,
            valid_from=orm.valid_from,
            valid_until=orm.valid_until,
            superseded_by=orm.superseded_by,
            created_by=orm.created_by,
            version=orm.version,
            metadata=orm.metadata_json,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )