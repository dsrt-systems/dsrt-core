"""Unit tests for Hybrid Retrieval Engine and Ranking (C4 §12-17)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from schemas.domain.enums import MemoryImportance, MemoryScope, MemoryType, MemoryVerificationState
from schemas.domain.memory import Memory, MemoryQuery, MemoryCreate

from core.memory.retrieval.ranking import HybridRanker, RankingWeights
from core.memory.retrieval.engine import HybridRetrievalEngine
from core.memory.store import MemoryStore
from core.memory.embeddings.store import EmbeddingStore
from core.repositories import MemoryRepository, OrganizationRepository
from core.storage.database import db_manager


def _make_mem(id: str, content: str, days_old: int = 0, imp=MemoryImportance.NORMAL, scope=MemoryScope.PROJECT) -> Memory:
    dt = datetime.now(timezone.utc) - timedelta(days=days_old)
    return Memory(
        id=id,
        organization_id="org_test",
        scope_type=scope,
        memory_type=MemoryType.SEMANTIC,
        content=content,
        importance=imp,
        verification_state=MemoryVerificationState.UNVERIFIED,
        created_at=dt,
        updated_at=dt,
        observed_at=dt,
    )


class TestHybridRanker:
    def test_ranking_weights_applied_correctly(self):
        ranker = HybridRanker()
        
        m1 = _make_mem("m1", "Test", imp=MemoryImportance.CRITICAL, scope=MemoryScope.PROJECT)
        
        # Simulating vector retrieval candidate with high similarity
        vector_cands = [{"memory_id": "m1", "similarity": 0.9, "memory_obj": m1}]
        
        results = ranker.rank_and_merge(vector_cands, [], [], MemoryScope.PROJECT, limit=10)
        assert len(results) == 1
        
        res = results[0]
        assert res.retrieval_method == "vector"
        assert res.relevance_score > 0.0
        
        # Verify specific components influenced score
        # Base similarity: 0.9 * 0.40 = 0.36
        # Importance (Critical): 1.0 * 0.10 = 0.10
        # Scope (Match): 1.0 * 0.10 = 0.10
        assert res.relevance_score >= 0.50

    def test_merges_and_deduplicates_candidates(self):
        ranker = HybridRanker()
        
        m1 = _make_mem("m1", "Common")
        m2 = _make_mem("m2", "Only Keyword")
        
        vector_cands = [{"memory_id": "m1", "similarity": 0.8, "memory_obj": m1}]
        keyword_cands = [m1, m2]
        
        results = ranker.rank_and_merge(vector_cands, keyword_cands, [], MemoryScope.PROJECT, limit=10)
        
        assert len(results) == 2
        # m1 was in both, should be 'hybrid'
        m1_res = next(r for r in results if r.memory.id == "m1")
        assert m1_res.retrieval_method == "hybrid"
        
        # m2 was only keyword
        m2_res = next(r for r in results if r.memory.id == "m2")
        assert m2_res.retrieval_method == "keyword"

    def test_temporal_decay_favors_recent_memories(self):
        ranker = HybridRanker()
        
        # Exact same data, different ages
        m_new = _make_mem("new", "Content", days_old=0)
        m_old = _make_mem("old", "Content", days_old=60)
        
        vector_cands = [
            {"memory_id": "new", "similarity": 0.8, "memory_obj": m_new},
            {"memory_id": "old", "similarity": 0.8, "memory_obj": m_old},
        ]
        
        results = ranker.rank_and_merge(vector_cands, [], [], MemoryScope.PROJECT, limit=10)
        assert results[0].memory.id == "new"
        assert results[0].relevance_score > results[1].relevance_score


@pytest.mark.asyncio
class TestHybridRetrievalEngine:
    async def test_engine_executes_hybrid_search(self):
        async with db_manager.session() as session:
            org_repo = OrganizationRepository(session)
            suffix = uuid.uuid4().hex[:8]
            org = await org_repo.create(name=f"Org {suffix}", slug=f"org-ret-{suffix}")

            mem_repo = MemoryRepository(session)
            mem_store = MemoryStore(mem_repo)
            emb_store = EmbeddingStore(session)
            
            engine = HybridRetrievalEngine(mem_repo, emb_store)

            # Seed data
            m1 = await mem_store.write(
                organization_id=org.id,
                proposal=MemoryCreate(
                    memory_type=MemoryType.SEMANTIC,
                    content="Specialized routing uses the Model Fabric.",
                    scope=MemoryScope.PROJECT,
                    importance=MemoryImportance.IMPORTANT,
                ),
            )
            await emb_store.create_embedding(m1.id, m1.content)

            # Query
            query = MemoryQuery(
                query="routing model fabric",
                scope=MemoryScope.PROJECT,
                limit=5,
            )

            response = await engine.search(org.id, query)
            
            assert response.total_candidates > 0
            assert response.retrieval_time_ms > 0
            assert response.results[0].memory.id == m1.id
            assert response.results[0].retrieval_method in ("vector", "hybrid", "keyword")