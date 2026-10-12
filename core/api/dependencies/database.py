"""Database session dependency."""

from __future__ import annotations

from typing import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.storage.database import db_manager


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a transactional session per request."""
    async with db_manager.session() as session:
        yield session


# Type alias for cleaner router signatures.
SessionDep = Depends(get_session)
