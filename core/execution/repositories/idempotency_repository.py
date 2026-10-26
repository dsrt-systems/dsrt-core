"""Idempotency key repository for execution deduplication."""

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.cost_ledger import IdempotencyKeyORM


class IdempotencyRepository:
    """Async repository for idempotency protection."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_key(
        self, organization_id: str, key_hash: str
    ) -> Optional[IdempotencyKeyORM]:
        now = datetime.now(timezone.utc)
        stmt = select(IdempotencyKeyORM).where(
            IdempotencyKeyORM.organization_id == organization_id,
            IdempotencyKeyORM.key_hash == key_hash,
            IdempotencyKeyORM.expires_at > now,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_key(
        self,
        organization_id: str,
        key_hash: str,
        key_string: str,
        execution_id: str,
        request_hash: str,
        ttl_seconds: int = 86400,
    ) -> IdempotencyKeyORM:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)
        idk_id = new_id(IdPrefix.C10_IDEMPOTENCY_KEY)

        orm = IdempotencyKeyORM(
            id=idk_id,
            key_hash=key_hash,
            key_string=key_string,
            organization_id=organization_id,
            execution_id=execution_id,
            request_hash=request_hash,
            response_payload=None,
            created_at=now,
            expires_at=expires_at,
        )
        self.session.add(orm)
        await self.session.commit()
        await self.session.refresh(orm)
        return orm

    async def complete_key(
        self, key_id: str, response_payload: Dict
    ) -> Optional[IdempotencyKeyORM]:
        stmt = (
            update(IdempotencyKeyORM)
            .where(IdempotencyKeyORM.id == key_id)
            .values(response_payload=response_payload)
        )
        await self.session.execute(stmt)
        await self.session.commit()

        stmt_get = select(IdempotencyKeyORM).where(IdempotencyKeyORM.id == key_id)
        res = await self.session.execute(stmt_get)
        return res.scalar_one_or_none()