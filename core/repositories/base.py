"""Repository base class."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class Repository:
    """Base class — holds the session and provides shared utilities."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session
