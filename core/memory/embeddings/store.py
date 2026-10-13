"""
Embedding Store (C4 §37).

Persists and queries vector embeddings in PostgreSQL via pgvector.
Model-independent — works with any embedding provider.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.memory.embeddings.generator import EmbeddingGenerator
from core.observability.logging import get_logger
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.memory import MemoryEmbeddingORM, MemoryORM


logger = get_logger("dsrt.memory.embeddings.store")


class EmbeddingStore:
    """Stores and queries memory embeddings."""

    def __init__(
        self,
        session: AsyncSession,
        generator: EmbeddingGenerator | None = None,
    ) -> None:
        self._session = session
        self._generator = generator or EmbeddingGenerator()

    @property
    def provider(self) -> str:
        """The embedding provider strategy in use."""
        return self._generator.provider

    async def create_embedding(
        self, memory_id: str, content: str,
    ) -> MemoryEmbeddingORM:
        """Generate and store an embedding for a memory."""
        vector = await self._generator.generate(content)
        vector_str = json.dumps(vector)

        embedding = MemoryEmbeddingORM(
            id=new_id(IdPrefix.MEMORY_EMBEDDING),
            memory_id=memory_id,
            embedding=vector_str,
            embedding_model=f"{self._generator.provider}:{self._generator.model_identifier}",
            embedding_dimensions=self._generator.dimensions,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(embedding)
        await self._session.flush()

        logger.debug(
            "embedding_created",
            memory_id=memory_id,
            provider=self._generator.provider,
            dimensions=self._generator.dimensions,
        )
        return embedding

    async def get_embedding(
        self, memory_id: str,
    ) -> MemoryEmbeddingORM | None:
        """Get the latest embedding for a memory."""
        stmt = (
            select(MemoryEmbeddingORM)
            .where(MemoryEmbeddingORM.memory_id == memory_id)
            .order_by(MemoryEmbeddingORM.created_at.desc())
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def search_similar(
        self,
        query_text: str,
        *,
        organization_id: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        memory_type: str | None = None,
        limit: int = 10,
        min_similarity: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Find memories most semantically similar to query text.

        Returns dicts with all fields needed by HybridRanker (C4.11 fix).
        """
        query_vector = await self._generator.generate(query_text)

        stmt = (
            select(MemoryEmbeddingORM, MemoryORM)
            .join(MemoryORM, MemoryEmbeddingORM.memory_id == MemoryORM.id)
            .where(
                MemoryORM.organization_id == organization_id,
                MemoryORM.status.in_(["ACTIVE", "UPDATED"]),
            )
        )

        if scope_type:
            stmt = stmt.where(MemoryORM.scope_type == scope_type)
        if scope_id:
            stmt = stmt.where(MemoryORM.scope_id == scope_id)
        if memory_type:
            stmt = stmt.where(MemoryORM.memory_type == memory_type)

        stmt = stmt.limit(limit * 5)

        res = await self._session.execute(stmt)
        rows = res.all()

        results: list[dict[str, Any]] = []
        for emb_orm, mem_orm in rows:
            if not emb_orm.embedding:
                continue

            try:
                stored_vector = json.loads(emb_orm.embedding)
            except (json.JSONDecodeError, TypeError):
                continue

            similarity = self._cosine_similarity(query_vector, stored_vector)

            if similarity >= min_similarity:
                results.append({
                    "memory_id": mem_orm.id,
                    "similarity": round(similarity, 6),
                    "content": mem_orm.content,
                    "memory_type": mem_orm.memory_type,
                    "scope_type": mem_orm.scope_type,
                    "scope_id": mem_orm.scope_id,
                    "importance": mem_orm.importance,
                    "status": mem_orm.status,
                    "confidence": mem_orm.confidence,
                    "verification_state": mem_orm.verification_state,
                    "observed_at": mem_orm.observed_at.isoformat() if mem_orm.observed_at else None,
                    "valid_from": mem_orm.valid_from.isoformat() if mem_orm.valid_from else None,
                    "valid_until": mem_orm.valid_until.isoformat() if mem_orm.valid_until else None,
                    "source_type": mem_orm.source_type,
                    "source_id": mem_orm.source_id,
                    "created_at": mem_orm.created_at.isoformat() if mem_orm.created_at else None,
                    "version": mem_orm.version,
                })

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]

    async def update_embedding(
        self, memory_id: str, content: str,
    ) -> MemoryEmbeddingORM:
        """Regenerate embedding after memory content update."""
        existing = await self.get_embedding(memory_id)
        if existing:
            await self._session.delete(existing)
            await self._session.flush()

        return await self.create_embedding(memory_id, content)

    async def delete_embeddings(self, memory_id: str) -> int:
        """Delete all embeddings for a memory."""
        stmt = select(MemoryEmbeddingORM).where(
            MemoryEmbeddingORM.memory_id == memory_id,
        )
        res = await self._session.execute(stmt)
        embeddings = list(res.scalars().all())
        count = len(embeddings)
        for emb in embeddings:
            await self._session.delete(emb)
        await self._session.flush()
        return count

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(a) != len(b) or not a:
            return 0.0

        dot_product = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(x * x for x in b))

        if mag_a == 0 or mag_b == 0:
            return 0.0

        return dot_product / (mag_a * mag_b)