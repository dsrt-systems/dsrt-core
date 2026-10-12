"""
Memory Retention Enforcer (C4 §24-25).

Background process that enforces TTLs and transitions stale memories
to the EXPIRED state.
"""

from __future__ import annotations

from core.observability.logging import get_logger
from core.repositories.memory_repository import MemoryRepository


logger = get_logger("dsrt.memory.retention")


class RetentionEnforcer:
    """Enforces expiration of time-sensitive memories."""

    def __init__(self, repo: MemoryRepository) -> None:
        self._repo = repo

    async def enforce_expiration(self, organization_id: str) -> int:
        """Find all ACTIVE/UPDATED memories past valid_until and mark EXPIRED.

        Returns:
            The number of memories expired.
        """
        try:
            expired_count = await self._repo.expire_stale(organization_id)
            if expired_count > 0:
                logger.info(
                    "memory_expiration_enforced",
                    organization_id=organization_id,
                    expired_count=expired_count,
                )
            return expired_count
        except Exception as e:
            logger.error(
                "memory_expiration_failed",
                organization_id=organization_id,
                error=str(e),
            )
            return 0