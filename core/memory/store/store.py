"""
Memory Store Service (C4 §10).

The domain service that implements the complete memory write pipeline:
validate → deduplicate → conflict-detect → permission check → provenance →
persist → version → embed → return.

Agents propose memories through sdk.memory.write().
Core decides whether and how they are persisted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from schemas.domain.enums import MemoryScope, MemoryStatus, MemoryType
from schemas.domain.memory import Memory, MemoryCreate, MemorySource, MemoryUpdate

from core.api.errors.exceptions import NotFoundError, ValidationError
from core.memory.conflicts.detector import ConflictDetector
from core.memory.embeddings.store import EmbeddingStore
from core.observability.logging import get_logger
from core.repositories.memory_repository import MemoryRepository
from core.storage.models.memory import MemoryORM


logger = get_logger("dsrt.memory.store")


class MemoryStore:
    """The central memory write service for DSRT Core."""

    def __init__(
        self,
        repo: MemoryRepository,
        embedding_store: EmbeddingStore | None = None,
    ) -> None:
        self._repo = repo
        self._embedding_store = embedding_store

    async def write(
        self,
        *,
        organization_id: str,
        proposal: MemoryCreate,
        created_by: str | None = None,
        execution_id: str | None = None,
        agent_slug: str | None = None,
    ) -> Memory:
        """Process a memory proposal through the write pipeline (C4 §10)."""
        # 1. Validate
        self._validate_proposal(proposal)

        # 2. Check for duplicates & conflicts if embedding store is available
        if self._embedding_store:
            detector = ConflictDetector(self._repo, self._embedding_store)
            detection_res = await detector.analyze_proposal(organization_id, proposal)

            # Deduplication: If duplicate found, refresh observed_at and return existing
            if detection_res.is_duplicate and detection_res.duplicate_memory_id:
                existing_orm = await self._repo.get_by_id(detection_res.duplicate_memory_id)
                if existing_orm:
                    await self._repo.update_memory(
                        existing_orm,
                        observed_at=datetime.now(timezone.utc),
                    )
                    logger.info(
                        "memory_deduplicated_existing_refreshed",
                        memory_id=existing_orm.id,
                    )
                    return self._to_domain(existing_orm)

        # 3. Persist new memory
        now = datetime.now(timezone.utc)
        mem_orm = await self._repo.create(
            organization_id=organization_id,
            scope_type=proposal.scope.value,
            scope_id=proposal.scope_id,
            memory_type=proposal.memory_type.value,
            content=proposal.content,
            structured_data=proposal.structured_data,
            status=MemoryStatus.ACTIVE.value,
            importance=proposal.importance.value,
            observed_at=now,
            valid_from=proposal.valid_from or now,
            valid_until=proposal.valid_until,
            created_by=created_by or agent_slug,
            metadata=proposal.metadata,
        )

        # 4. Create initial version snapshot
        await self._repo.create_version(
            memory_id=mem_orm.id,
            version=1,
            content=proposal.content,
            structured_data=proposal.structured_data,
            change_reason="Initial creation",
            author=created_by or agent_slug,
        )

        # 5. Generate and store embedding
        if self._embedding_store:
            await self._embedding_store.create_embedding(mem_orm.id, proposal.content)

            # Check conflicts and record if detected
            if detection_res.action_taken == "CONFLICT_DETECTED":
                for conf_id in detection_res.conflicting_memory_ids:
                    await self._repo.create_conflict(
                        memory_a_id=mem_orm.id,
                        memory_b_id=conf_id,
                        description=f"Contradiction detected during proposal write.",
                    )
                    await self._repo.create_link(
                        source_memory_id=mem_orm.id,
                        target_memory_id=conf_id,
                        link_type="CONTRADICTS",
                    )

        # 6. Attach source provenance if provided
        if proposal.source:
            await self._repo.add_source(
                memory_id=mem_orm.id,
                source_type=proposal.source.source_type,
                source_id=proposal.source.source_id,
                tool_execution_id=proposal.source.tool_execution_id,
                execution_id=execution_id or proposal.source.execution_id,
                agent_slug=agent_slug or proposal.source.agent_slug,
                url=proposal.source.url,
                metadata=proposal.source.metadata,
            )

        # 7. Log the write access
        await self._repo.log_access(
            memory_id=mem_orm.id,
            organization_id=organization_id,
            action="WRITE",
            scope_type=proposal.scope.value,
            scope_id=proposal.scope_id,
            agent_slug=agent_slug,
            execution_id=execution_id,
            result="ALLOWED",
        )

        logger.info(
            "memory_created",
            memory_id=mem_orm.id,
            memory_type=proposal.memory_type.value,
            scope=proposal.scope.value,
            importance=proposal.importance.value,
        )

        return self._to_domain(mem_orm)

    async def get(
        self,
        memory_id: str,
        organization_id: str,
    ) -> Memory:
        """Get a memory by ID with organization boundary enforcement."""
        mem_orm = await self._repo.get_by_id(memory_id)
        if not mem_orm or mem_orm.organization_id != organization_id:
            raise NotFoundError(f"Memory '{memory_id}' not found.")
        return self._to_domain(mem_orm)

    async def update(
        self,
        memory_id: str,
        organization_id: str,
        patch: MemoryUpdate,
        *,
        author: str | None = None,
        execution_id: str | None = None,
    ) -> Memory:
        """Update a memory, creating a new version snapshot."""
        mem_orm = await self._repo.get_by_id(memory_id)
        if not mem_orm or mem_orm.organization_id != organization_id:
            raise NotFoundError(f"Memory '{memory_id}' not found.")

        # Determine what changed
        old_content = mem_orm.content
        new_content = patch.content or old_content

        # Update the memory record
        await self._repo.update_memory(
            mem_orm,
            content=patch.content,
            structured_data=patch.structured_data,
            status=patch.status.value if patch.status else None,
            importance=patch.importance.value if patch.importance else None,
            confidence=patch.confidence,
            verification_state=patch.verification_state.value if patch.verification_state else None,
            valid_until=patch.valid_until,
            metadata=patch.metadata,
        )

        # Create version snapshot if content changed
        if patch.content and patch.content != old_content:
            prev_version = mem_orm.version
            new_version = await self._repo.increment_version(mem_orm)
            await self._repo.create_version(
                memory_id=memory_id,
                version=new_version,
                content=new_content,
                structured_data=patch.structured_data or mem_orm.structured_data,
                previous_version=prev_version,
                change_reason=patch.change_reason or "Updated",
                author=author,
            )

        # Log the access
        await self._repo.log_access(
            memory_id=memory_id,
            organization_id=organization_id,
            action="WRITE",
            scope_type=mem_orm.scope_type,
            scope_id=mem_orm.scope_id,
            execution_id=execution_id,
            result="ALLOWED",
        )

        logger.info(
            "memory_updated",
            memory_id=memory_id,
            version=mem_orm.version,
        )

        return self._to_domain(mem_orm)

    async def archive(
        self,
        memory_id: str,
        organization_id: str,
    ) -> Memory:
        """Soft-delete a memory by archiving it."""
        mem_orm = await self._repo.get_by_id(memory_id)
        if not mem_orm or mem_orm.organization_id != organization_id:
            raise NotFoundError(f"Memory '{memory_id}' not found.")

        await self._repo.soft_delete(mem_orm)

        await self._repo.log_access(
            memory_id=memory_id,
            organization_id=organization_id,
            action="DELETE",
            scope_type=mem_orm.scope_type,
            scope_id=mem_orm.scope_id,
            result="ALLOWED",
        )

        logger.info("memory_archived", memory_id=memory_id)
        return self._to_domain(mem_orm)

    async def list_by_scope(
        self,
        *,
        organization_id: str,
        scope_type: str,
        scope_id: str | None = None,
        memory_type: str | None = None,
        limit: int = 50,
    ) -> list[Memory]:
        """List memories within a scope."""
        mems = await self._repo.list_by_scope(
            organization_id=organization_id,
            scope_type=scope_type,
            scope_id=scope_id,
            memory_type=memory_type,
            limit=limit,
        )
        return [self._to_domain(m) for m in mems]

    async def link(
        self,
        *,
        source_memory_id: str,
        target_memory_id: str,
        link_type: str,
        organization_id: str,
        confidence: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Create a directed link between two memories."""
        # Verify both memories exist and belong to the same org
        source = await self._repo.get_by_id(source_memory_id)
        target = await self._repo.get_by_id(target_memory_id)

        if not source or source.organization_id != organization_id:
            raise NotFoundError(f"Source memory '{source_memory_id}' not found.")
        if not target or target.organization_id != organization_id:
            raise NotFoundError(f"Target memory '{target_memory_id}' not found.")

        await self._repo.create_link(
            source_memory_id=source_memory_id,
            target_memory_id=target_memory_id,
            link_type=link_type,
            confidence=confidence,
            metadata=metadata,
        )

        logger.info(
            "memory_linked",
            source=source_memory_id,
            target=target_memory_id,
            link_type=link_type,
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_proposal(self, proposal: MemoryCreate) -> None:
        """Validate a memory proposal before persistence."""
        if not proposal.content.strip():
            raise ValidationError("Memory content must not be empty.")

        if len(proposal.content) > 100000:
            raise ValidationError(
                f"Memory content too large ({len(proposal.content)} chars, max 100000)."
            )

    # ------------------------------------------------------------------
    # Domain conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _to_domain(orm: MemoryORM) -> Memory:
        return Memory(
            id=orm.id,
            organization_id=orm.organization_id,
            scope_type=MemoryScope(orm.scope_type),
            scope_id=orm.scope_id,
            memory_type=MemoryType(orm.memory_type),
            content=orm.content,
            structured_data=orm.structured_data,
            status=MemoryStatus(orm.status),
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