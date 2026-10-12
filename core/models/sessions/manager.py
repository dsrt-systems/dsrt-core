"""
Model Session Manager (C2 §20-21).

Manages continuity and seamless model switching.
"""

from __future__ import annotations

from core.api.errors.exceptions import NotFoundError
from core.observability.logging import get_logger
from core.repositories.session_repository import SessionRepository
from schemas.domain.session import (
    ModelCheckpoint,
    ModelCheckpointCreate,
    ModelSession,
    ModelSessionCreate,
)


logger = get_logger("dsrt.models.sessions.manager")


class ModelSessionManager:
    def __init__(self, session_repo: SessionRepository) -> None:
        self._repo = session_repo

    async def get_or_create_active_session(
        self, execution_id: str, target_model_id: str, target_provider_id: str
    ) -> ModelSession:
        """
        Get the active session. If the target model differs from the active session,
        perform a MODEL SWITCH (C2 §21).
        """
        active_orm = await self._repo.get_active_session(execution_id)

        if active_orm:
            if active_orm.model_id == target_model_id:
                # Still using the same model, continue session
                return ModelSession(
                    id=active_orm.id,
                    execution_id=active_orm.execution_id,
                    model_id=active_orm.model_id,
                    provider_id=active_orm.provider_id,
                    status=active_orm.status,
                    created_at=active_orm.created_at,
                    updated_at=active_orm.updated_at,
                )
            else:
                # Model mismatch! We are switching models.
                logger.info(
                    "model_switch_initiated",
                    execution_id=execution_id,
                    from_model=active_orm.model_id,
                    to_model=target_model_id,
                )
                await self._repo.close_active_sessions(execution_id, new_status="switched")

        # Create new active session for the new model
        new_orm = await self._repo.create_session(
            execution_id=execution_id,
            model_id=target_model_id,
            provider_id=target_provider_id,
        )
        
        logger.info(
            "model_session_created",
            session_id=new_orm.id,
            execution_id=execution_id,
            model_id=target_model_id,
        )

        return ModelSession(
            id=new_orm.id,
            execution_id=new_orm.execution_id,
            model_id=new_orm.model_id,
            provider_id=new_orm.provider_id,
            status=new_orm.status,
            created_at=new_orm.created_at,
            updated_at=new_orm.updated_at,
        )

    async def create_checkpoint(self, data: ModelCheckpointCreate) -> ModelCheckpoint:
        """Record a reproducible point in time for the session."""
        chk_orm = await self._repo.create_checkpoint(
            session_id=data.session_id,
            request_id=data.request_id,
            context_hash=data.context_hash,
            canonical_state_hash=data.canonical_state_hash,
            output_hash=data.output_hash,
            metadata=data.metadata,
        )
        
        logger.debug(
            "model_checkpoint_created",
            session_id=data.session_id,
            checkpoint_id=chk_orm.id,
        )

        return ModelCheckpoint(
            id=chk_orm.id,
            session_id=chk_orm.session_id,
            request_id=chk_orm.request_id,
            context_hash=chk_orm.context_hash,
            canonical_state_hash=chk_orm.canonical_state_hash,
            output_hash=chk_orm.output_hash,
            metadata=chk_orm.metadata_payload,
            created_at=chk_orm.created_at,
            updated_at=chk_orm.updated_at,
        )