"""User repository — all user-table access flows through this."""

from __future__ import annotations

from sqlalchemy import select

from core.repositories.base import Repository
from core.storage.models import User


class UserRepository(Repository):
    async def get_by_id(self, user_id: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.id == user_id),
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        normalized = email.strip().lower()
        result = await self._session.execute(
            select(User).where(User.email == normalized),
        )
        return result.scalar_one_or_none()

    async def email_exists(self, email: str) -> bool:
        return (await self.get_by_email(email)) is not None

    async def create(
        self,
        *,
        email: str,
        display_name: str,
        password_hash: str,
    ) -> User:
        user = User(
            email=email.strip().lower(),
            display_name=display_name,
            password_hash=password_hash,
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def update_last_login(self, user: User) -> None:
        from core.storage.models.mixins import utcnow

        user.last_login_at = utcnow()
        await self._session.flush()
