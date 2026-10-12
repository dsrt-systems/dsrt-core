"""Unit tests for Embedding Generator and Store (C4 §13, §37)."""

from __future__ import annotations

import math
import uuid

import pytest

from core.memory.embeddings.generator import EmbeddingGenerator
from core.memory.embeddings.store import EmbeddingStore
from core.repositories import MemoryRepository, OrganizationRepository
from core.memory.store import MemoryStore
from core.storage.database import db_manager
from schemas.domain.enums import MemoryScope, MemoryType
from schemas.domain.memory import MemoryCreate


class TestEmbeddingGenerator:
    @pytest.mark.asyncio
    async def test_generates_correct_dimensions(self):
        gen = EmbeddingGenerator(provider="local-hash", dimensions=384)
        vector = await gen.generate("Hello world")
        assert len(vector) == 384
        assert all(isinstance(v, float) for v in vector)

    @pytest.mark.asyncio
    async def test_deterministic_for_same_input(self):
        gen = EmbeddingGenerator(provider="local-hash", dimensions=128)
        v1 = await gen.generate("Consistent input text")
        v2 = await gen.generate("Consistent input text")
        assert v1 == v2

    @pytest.mark.asyncio
    async def test_different_inputs_produce_different_vectors(self):
        gen = EmbeddingGenerator(provider="local-hash", dimensions=128)
        v1 = await gen.generate("First text")
        v2 = await gen.generate("Completely different content")
        assert v1 != v2

    @pytest.mark.asyncio
    async def test_normalized_to_unit_length(self):
        gen = EmbeddingGenerator(provider="local-hash", dimensions=256)
        vector = await gen.generate("Test normalization")
        magnitude = math.sqrt(sum(v * v for v in vector))
        assert abs(magnitude - 1.0) < 0.001

    @pytest.mark.asyncio
    async def test_empty_input_returns_zero_vector(self):
        gen = EmbeddingGenerator(provider="local-hash", dimensions=64)
        vector = await gen.generate("")
        assert all(v == 0.0 for v in vector)

    @pytest.mark.asyncio
    async def test_batch_generation(self):
        gen = EmbeddingGenerator(provider="local-hash", dimensions=64)
        texts = ["Hello", "World", "Test"]
        vectors = await gen.generate_batch(texts)
        assert len(vectors) == 3
        assert all(len(v) == 64 for v in vectors)

    @pytest.mark.asyncio
    async def test_provider_property(self):
        gen = EmbeddingGenerator(provider="openai", model_identifier="text-embedding-3-small", dimensions=1536)
        assert gen.provider == "openai"
        assert gen.model_identifier == "text-embedding-3-small"
        assert gen.dimensions == 1536

    @pytest.mark.asyncio
    async def test_unknown_provider_falls_back_to_hash(self):
        gen = EmbeddingGenerator(provider="nonexistent_provider", dimensions=64)
        vector = await gen.generate("Test fallback")
        assert len(vector) == 64  # Falls back to hash, doesn't crash


class TestEmbeddingStore:
    @pytest.mark.asyncio
    async def test_create_and_retrieve_embedding(self):
        async with db_manager.session() as session:
            org_repo = OrganizationRepository(session)
            suffix = uuid.uuid4().hex[:8]
            org = await org_repo.create(name=f"Org {suffix}", slug=f"org-emb-{suffix}")

            mem_repo = MemoryRepository(session)
            mem_store = MemoryStore(mem_repo)
            memory = await mem_store.write(
                organization_id=org.id,
                proposal=MemoryCreate(
                    memory_type=MemoryType.SEMANTIC,
                    content="PostgreSQL is the primary database.",
                    scope=MemoryScope.PROJECT,
                ),
            )

            emb_store = EmbeddingStore(session)
            emb = await emb_store.create_embedding(memory.id, memory.content)
            assert emb.memory_id == memory.id
            assert emb.embedding is not None
            assert "local-hash" in emb.embedding_model

            fetched = await emb_store.get_embedding(memory.id)
            assert fetched is not None
            assert fetched.id == emb.id

    @pytest.mark.asyncio
    async def test_similarity_search_returns_results(self):
        async with db_manager.session() as session:
            org_repo = OrganizationRepository(session)
            suffix = uuid.uuid4().hex[:8]
            org = await org_repo.create(name=f"Org {suffix}", slug=f"org-sim-{suffix}")

            mem_repo = MemoryRepository(session)
            mem_store = MemoryStore(mem_repo)
            emb_store = EmbeddingStore(session)

            contents = [
                "PostgreSQL is used as the primary relational database.",
                "Redis is used for caching and working memory.",
                "The weather today is sunny and warm.",
                "DSRT Core uses pgvector for semantic search.",
            ]

            for content in contents:
                memory = await mem_store.write(
                    organization_id=org.id,
                    proposal=MemoryCreate(
                        memory_type=MemoryType.SEMANTIC,
                        content=content,
                        scope=MemoryScope.PROJECT,
                    ),
                )
                await emb_store.create_embedding(memory.id, memory.content)

            # NOTE: Because local-hash is NOT semantically meaningful, we must
            # search using an exact string to get a high similarity score in tests.
            target_query = "PostgreSQL is used as the primary relational database."
            results = await emb_store.search_similar(
                target_query,
                organization_id=org.id,
                limit=3,
            )

            assert len(results) >= 1
            # Exact match should give similarity ~ 1.0
            assert results[0]["similarity"] > 0.99

    @pytest.mark.asyncio
    async def test_scope_filtering_in_search(self):
        async with db_manager.session() as session:
            org_repo = OrganizationRepository(session)
            suffix = uuid.uuid4().hex[:8]
            org = await org_repo.create(name=f"Org {suffix}", slug=f"org-sf-{suffix}")

            mem_repo = MemoryRepository(session)
            mem_store = MemoryStore(mem_repo)
            emb_store = EmbeddingStore(session)

            project_id = f"proj_{suffix}"
            
            target_text = f"Database decision for project {suffix}."

            # Memory in target project
            m1 = await mem_store.write(
                organization_id=org.id,
                proposal=MemoryCreate(
                    memory_type=MemoryType.SEMANTIC,
                    content=target_text,
                    scope=MemoryScope.PROJECT,
                    scope_id=project_id,
                ),
            )
            await emb_store.create_embedding(m1.id, m1.content)

            # Memory in different project
            m2 = await mem_store.write(
                organization_id=org.id,
                proposal=MemoryCreate(
                    memory_type=MemoryType.SEMANTIC,
                    content="Database decision for other project.",
                    scope=MemoryScope.PROJECT,
                    scope_id="proj_other",
                ),
            )
            await emb_store.create_embedding(m2.id, m2.content)

            # Search scoped to target project (use exact string for local-hash)
            results = await emb_store.search_similar(
                target_text,
                organization_id=org.id,
                scope_type="project",
                scope_id=project_id,
                limit=5,
            )

            memory_ids = [r["memory_id"] for r in results]
            assert m1.id in memory_ids
            assert m2.id not in memory_ids  # Filtered by scope_id

    @pytest.mark.asyncio
    async def test_update_embedding(self):
        async with db_manager.session() as session:
            org_repo = OrganizationRepository(session)
            suffix = uuid.uuid4().hex[:8]
            org = await org_repo.create(name=f"Org {suffix}", slug=f"org-ue-{suffix}")

            mem_repo = MemoryRepository(session)
            mem_store = MemoryStore(mem_repo)
            memory = await mem_store.write(
                organization_id=org.id,
                proposal=MemoryCreate(
                    memory_type=MemoryType.SEMANTIC,
                    content="Original content about databases.",
                    scope=MemoryScope.PROJECT,
                ),
            )

            emb_store = EmbeddingStore(session)
            emb1 = await emb_store.create_embedding(memory.id, memory.content)
            old_id = emb1.id

            # Update embedding with new content
            emb2 = await emb_store.update_embedding(
                memory.id, "Updated content about vector search.",
            )
            assert emb2.id != old_id  # New embedding created