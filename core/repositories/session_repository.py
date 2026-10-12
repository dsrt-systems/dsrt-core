"""
Session Repository.
"""

from __future__ import annotations

from sqlalchemy import select, update

from core.repositories.base import Repository
from core.storage.models.session import ModelCheckpointORM, ModelSessionORM


class SessionRepository(Repository):
    
    async def create_session(self, execution_id: str, model_id: str, provider_id: str) -> ModelSessionORM:
        session = ModelSessionORM(
            execution_id=execution_id,
            model_id=model_id,
            provider_id=provider_id,
            status="active"
        )
        self._session.add(session)
        await self._session.flush()
        return session

    async def get_active_session(self, execution_id: str) -> ModelSessionORM | None:
        result = await self._session.execute(
            select(ModelSessionORM)
            .where(
                ModelSessionORM.execution_id == execution_id,
                ModelSessionORM.status == "active"
            )
        )
        return result.scalar_one_or_none()

    async def close_active_sessions(self, execution_id: str, new_status: str = "switched") -> None:
        """Mark all active sessions for this execution as switched/closed."""
        await self._session.execute(
            update(ModelSessionORM)
            .where(
                ModelSessionORM.execution_id == execution_id,
                ModelSessionORM.status == "active"
            )
            .values(status=new_status)
        )
        await self._session.flush()

    async def create_checkpoint(
        self, 
        session_id: str, 
        request_id: str, 
        context_hash: str, 
        canonical_state_hash: str, 
        output_hash: str, 
        metadata: dict
    ) -> ModelCheckpointORM:
        chk = ModelCheckpointORM(
            session_id=session_id,
            request_id=request_id,
            context_hash=context_hash,
            canonical_state_hash=canonical_state_hash,
            output_hash=output_hash,
            metadata_payload=metadata,
        )
        self._session.add(chk)
        await self._session.flush()
        return chk