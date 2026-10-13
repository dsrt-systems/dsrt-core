"""
Memory REST API (C4 §54).

Provides memory CRUD and retrieval endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.api.dependencies.database import get_session
from core.api.dependencies.security import get_security_context, require_active_organization
from core.memory.embeddings.store import EmbeddingStore
from core.memory.retrieval.engine import HybridRetrievalEngine
from core.memory.store import MemoryStore
from core.repositories import MemoryRepository
from core.security.context import SecurityContext
from schemas.api.memory import (
    MemoryCreateRequest,
    MemoryListResponse,
    MemoryRetrieveRequest,
    MemoryUpdateRequest,
)
from schemas.domain.memory import Memory, MemoryQuery, MemoryRetrievalResponse


router = APIRouter(prefix="/api/v1/memories", tags=["memory"])


def _get_store(session: AsyncSession) -> MemoryStore:
    repo = MemoryRepository(session)
    emb_store = EmbeddingStore(session)
    return MemoryStore(repo, embedding_store=emb_store)


def _get_retrieval(session: AsyncSession) -> HybridRetrievalEngine:
    repo = MemoryRepository(session)
    emb_store = EmbeddingStore(session)
    return HybridRetrievalEngine(repo, emb_store)


@router.post("", status_code=201)
async def create_memory(
    body: MemoryCreateRequest,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Create a new memory."""
    store = _get_store(session)
    mem = await store.write(
        organization_id=ctx.active_organization_id,
        proposal=body,
        created_by=ctx.user_id,
    )
    return mem.model_dump()


@router.get("/{memory_id}")
async def get_memory(
    memory_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Get a specific memory."""
    store = _get_store(session)
    mem = await store.get(memory_id, ctx.active_organization_id)
    return mem.model_dump()


@router.patch("/{memory_id}")
async def update_memory(
    memory_id: str,
    body: MemoryUpdateRequest,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Update a memory."""
    store = _get_store(session)
    mem = await store.update(
        memory_id, ctx.active_organization_id, body, author=ctx.user_id,
    )
    return mem.model_dump()


@router.delete("/{memory_id}")
async def archive_memory(
    memory_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Archive (soft-delete) a memory."""
    store = _get_store(session)
    mem = await store.archive(memory_id, ctx.active_organization_id)
    return mem.model_dump()


@router.post("/retrieve")
async def retrieve_memories(
    body: MemoryRetrieveRequest,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Retrieve relevant memories using hybrid search."""
    engine = _get_retrieval(session)
    query = MemoryQuery(
        query=body.query,
        scope=body.scope,
        scope_id=body.scope_id,
        memory_types=body.memory_types,
        limit=body.limit,
    )
    resp = await engine.search(ctx.active_organization_id, query)
    return resp.model_dump()