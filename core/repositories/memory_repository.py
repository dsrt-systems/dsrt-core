"""
Memory Repository.

Handles all database operations for memories, versions, sources, links, and conflicts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import selectinload

from core.repositories.base import Repository
from core.storage.models.memory import (
    MemoryConflictORM,
    MemoryLinkORM,
    MemoryORM,
    MemorySourceORM,
    MemoryVersionORM,
)
from core.storage.models.memory_access import MemoryAccessLogORM
from core.storage.models.mixins import utcnow


class MemoryRepository(Repository):
    """Repository for memory lifecycle persistence."""

    # ------------------------------------------------------------------
    # Memory CRUD
    # ------------------------------------------------------------------

    async def create(
        self,
        *,
        organization_id: str,
        scope_type: str,
        scope_id: str | None = None,
        memory_type: str,
        content: str,
        structured_data: dict[str, Any] | None = None,
        status: str = "ACTIVE",
        importance: str = "normal",
        confidence: float | None = None,
        verification_state: str = "UNVERIFIED",
        source_type: str | None = None,
        source_id: str | None = None,
        observed_at: datetime | None = None,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        created_by: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryORM:
        """Create a new memory record."""
        mem = MemoryORM(
            organization_id=organization_id,
            scope_type=scope_type,
            scope_id=scope_id,
            memory_type=memory_type,
            content=content,
            structured_data=structured_data,
            status=status,
            importance=importance,
            confidence=confidence,
            verification_state=verification_state,
            source_type=source_type,
            source_id=source_id,
            observed_at=observed_at or utcnow(),
            valid_from=valid_from,
            valid_until=valid_until,
            created_by=created_by,
            version=1,
            metadata_json=metadata or {},
        )
        self._session.add(mem)
        await self._session.flush()
        return mem

    async def get_by_id(self, memory_id: str) -> MemoryORM | None:
        """Get a memory by primary key with eager-loaded relationships."""
        stmt = (
            select(MemoryORM)
            .where(MemoryORM.id == memory_id)
            .options(
                selectinload(MemoryORM.versions),
                selectinload(MemoryORM.sources),
                selectinload(MemoryORM.outgoing_links),
                selectinload(MemoryORM.incoming_links),
            )
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_by_scope(
        self,
        *,
        organization_id: str,
        scope_type: str,
        scope_id: str | None = None,
        memory_type: str | None = None,
        status: str | None = None,
        importance: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryORM]:
        """List memories within a scope boundary."""
        stmt = select(MemoryORM).where(
            MemoryORM.organization_id == organization_id,
            MemoryORM.scope_type == scope_type,
        )

        if scope_id is not None:
            stmt = stmt.where(MemoryORM.scope_id == scope_id)
        if memory_type is not None:
            stmt = stmt.where(MemoryORM.memory_type == memory_type)
        if status is not None:
            stmt = stmt.where(MemoryORM.status == status)
        else:
            # Default: exclude archived/expired/rejected
            stmt = stmt.where(
                MemoryORM.status.in_(["ACTIVE", "PROPOSED", "VALIDATING", "UPDATED"])
            )
        if importance is not None:
            stmt = stmt.where(MemoryORM.importance == importance)

        stmt = stmt.order_by(MemoryORM.created_at.desc()).limit(limit).offset(offset)
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def update_memory(
        self,
        memory: MemoryORM,
        *,
        content: str | None = None,
        structured_data: dict[str, Any] | None = None,
        status: str | None = None,
        importance: str | None = None,
        confidence: float | None = None,
        verification_state: str | None = None,
        observed_at: datetime | None = None,
        valid_until: datetime | None = None,
        superseded_by: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryORM:
        """Update fields on an existing memory."""
        if content is not None:
            memory.content = content
        if structured_data is not None:
            memory.structured_data = structured_data
        if status is not None:
            memory.status = status
        if importance is not None:
            memory.importance = importance
        if confidence is not None:
            memory.confidence = confidence
        if verification_state is not None:
            memory.verification_state = verification_state
        if observed_at is not None:
            memory.observed_at = observed_at
        if valid_until is not None:
            memory.valid_until = valid_until
        if superseded_by is not None:
            memory.superseded_by = superseded_by
        if metadata is not None:
            memory.metadata_json = metadata

        await self._session.flush()
        return memory

    async def increment_version(self, memory: MemoryORM) -> int:
        """Increment the version counter and return the new version number."""
        memory.version += 1
        await self._session.flush()
        return memory.version

    async def soft_delete(self, memory: MemoryORM) -> MemoryORM:
        """Soft delete by transitioning to ARCHIVED status."""
        memory.status = "ARCHIVED"
        await self._session.flush()
        return memory

    async def search_content(
        self,
        *,
        organization_id: str,
        query: str,
        scope_type: str | None = None,
        scope_id: str | None = None,
        memory_type: str | None = None,
        limit: int = 20,
    ) -> list[MemoryORM]:
        """Keyword search via PostgreSQL ILIKE across query terms."""
        terms = [t.strip() for t in query.split() if len(t.strip()) > 1]
        if not terms:
            terms = [query.strip()]

        term_clauses = [MemoryORM.content.ilike(f"%{t}%") for t in terms]

        stmt = select(MemoryORM).where(
            MemoryORM.organization_id == organization_id,
            MemoryORM.status.in_(["ACTIVE", "UPDATED"]),
            or_(*term_clauses),
        )

        if scope_type is not None:
            stmt = stmt.where(MemoryORM.scope_type == scope_type)
        if scope_id is not None:
            stmt = stmt.where(MemoryORM.scope_id == scope_id)
        if memory_type is not None:
            stmt = stmt.where(MemoryORM.memory_type == memory_type)

        stmt = stmt.order_by(MemoryORM.created_at.desc()).limit(limit)
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def search_temporal(
        self,
        *,
        organization_id: str,
        valid_at: datetime,
        scope_type: str | None = None,
        scope_id: str | None = None,
        limit: int = 20,
    ) -> list[MemoryORM]:
        """Find memories valid at a specific point in time."""
        stmt = select(MemoryORM).where(
            MemoryORM.organization_id == organization_id,
            MemoryORM.status.in_(["ACTIVE", "UPDATED"]),
            or_(
                MemoryORM.valid_from.is_(None),
                MemoryORM.valid_from <= valid_at,
            ),
            or_(
                MemoryORM.valid_until.is_(None),
                MemoryORM.valid_until >= valid_at,
            ),
        )

        if scope_type is not None:
            stmt = stmt.where(MemoryORM.scope_type == scope_type)
        if scope_id is not None:
            stmt = stmt.where(MemoryORM.scope_id == scope_id)

        stmt = stmt.order_by(MemoryORM.created_at.desc()).limit(limit)
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def expire_stale(
        self,
        organization_id: str,
        before: datetime | None = None,
    ) -> int:
        """Expire memories past their valid_until date."""
        cutoff = before or datetime.now(timezone.utc)
        stmt = (
            update(MemoryORM)
            .where(
                MemoryORM.organization_id == organization_id,
                MemoryORM.status.in_(["ACTIVE", "UPDATED"]),
                MemoryORM.valid_until.isnot(None),
                MemoryORM.valid_until <= cutoff,
            )
            .values(status="EXPIRED")
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount

    # ------------------------------------------------------------------
    # Memory Versions
    # ------------------------------------------------------------------

    async def create_version(
        self,
        *,
        memory_id: str,
        version: int,
        content: str,
        structured_data: dict[str, Any] | None = None,
        previous_version: int | None = None,
        change_reason: str = "",
        source_type: str | None = None,
        source_id: str | None = None,
        author: str | None = None,
    ) -> MemoryVersionORM:
        """Create an immutable version snapshot."""
        ver = MemoryVersionORM(
            memory_id=memory_id,
            version=version,
            content=content,
            structured_data=structured_data,
            previous_version=previous_version,
            change_reason=change_reason,
            source_type=source_type,
            source_id=source_id,
            author=author,
        )
        self._session.add(ver)
        await self._session.flush()
        return ver

    async def list_versions(self, memory_id: str) -> list[MemoryVersionORM]:
        """List all versions of a memory in chronological order."""
        stmt = (
            select(MemoryVersionORM)
            .where(MemoryVersionORM.memory_id == memory_id)
            .order_by(MemoryVersionORM.version.asc())
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    # ------------------------------------------------------------------
    # Memory Sources (Provenance)
    # ------------------------------------------------------------------

    async def add_source(
        self,
        *,
        memory_id: str,
        source_type: str,
        source_id: str | None = None,
        tool_execution_id: str | None = None,
        execution_id: str | None = None,
        agent_slug: str | None = None,
        url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemorySourceORM:
        """Attach a provenance source to a memory."""
        src = MemorySourceORM(
            memory_id=memory_id,
            source_type=source_type,
            source_id=source_id,
            tool_execution_id=tool_execution_id,
            execution_id=execution_id,
            agent_slug=agent_slug,
            url=url,
            metadata_json=metadata or {},
        )
        self._session.add(src)
        await self._session.flush()
        return src

    # ------------------------------------------------------------------
    # Memory Links
    # ------------------------------------------------------------------

    async def create_link(
        self,
        *,
        source_memory_id: str,
        target_memory_id: str,
        link_type: str,
        confidence: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryLinkORM:
        """Create a directed relationship between two memories."""
        link = MemoryLinkORM(
            source_memory_id=source_memory_id,
            target_memory_id=target_memory_id,
            link_type=link_type,
            confidence=confidence,
            metadata_json=metadata or {},
        )
        self._session.add(link)
        await self._session.flush()
        return link

    async def get_links(
        self, memory_id: str, direction: str = "outgoing",
    ) -> list[MemoryLinkORM]:
        """Get links for a memory. direction: 'outgoing' | 'incoming' | 'both'."""
        if direction == "outgoing":
            stmt = select(MemoryLinkORM).where(
                MemoryLinkORM.source_memory_id == memory_id
            )
        elif direction == "incoming":
            stmt = select(MemoryLinkORM).where(
                MemoryLinkORM.target_memory_id == memory_id
            )
        else:
            stmt = select(MemoryLinkORM).where(
                or_(
                    MemoryLinkORM.source_memory_id == memory_id,
                    MemoryLinkORM.target_memory_id == memory_id,
                )
            )
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    # ------------------------------------------------------------------
    # Memory Conflicts
    # ------------------------------------------------------------------

    async def create_conflict(
        self,
        *,
        memory_a_id: str,
        memory_b_id: str,
        conflict_type: str = "CONTRADICTION",
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> MemoryConflictORM:
        """Record a detected conflict between two memories."""
        conflict = MemoryConflictORM(
            memory_a_id=memory_a_id,
            memory_b_id=memory_b_id,
            conflict_type=conflict_type,
            description=description,
            metadata_json=metadata or {},
        )
        self._session.add(conflict)
        await self._session.flush()
        return conflict

    async def list_unresolved_conflicts(
        self, organization_id: str | None = None, limit: int = 50,
    ) -> list[MemoryConflictORM]:
        """List unresolved memory conflicts."""
        stmt = (
            select(MemoryConflictORM)
            .where(MemoryConflictORM.resolved == False)
            .order_by(MemoryConflictORM.created_at.desc())
            .limit(limit)
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    # ------------------------------------------------------------------
    # Access Logging
    # ------------------------------------------------------------------

    async def log_access(
        self,
        *,
        memory_id: str,
        organization_id: str,
        action: str,
        scope_type: str,
        scope_id: str | None = None,
        user_id: str | None = None,
        agent_slug: str | None = None,
        execution_id: str | None = None,
        result: str = "ALLOWED",
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryAccessLogORM:
        """Record an access log entry for audit trail."""
        log = MemoryAccessLogORM(
            memory_id=memory_id,
            organization_id=organization_id,
            user_id=user_id,
            agent_slug=agent_slug,
            execution_id=execution_id,
            action=action,
            scope_type=scope_type,
            scope_id=scope_id,
            result=result,
            reason=reason,
            metadata_json=metadata or {},
        )
        self._session.add(log)
        await self._session.flush()
        return log

    async def count_by_scope(
        self,
        organization_id: str,
        scope_type: str,
        scope_id: str | None = None,
    ) -> int:
        """Count active memories in a scope."""
        stmt = select(func.count(MemoryORM.id)).where(
            MemoryORM.organization_id == organization_id,
            MemoryORM.scope_type == scope_type,
            MemoryORM.status.in_(["ACTIVE", "UPDATED"]),
        )
        if scope_id is not None:
            stmt = stmt.where(MemoryORM.scope_id == scope_id)
        res = await self._session.execute(stmt)
        return res.scalar() or 0