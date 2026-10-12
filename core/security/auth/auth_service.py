"""
Auth Service — the orchestrator for registration and login.

This is the ONLY place where password material is compared. It emits normalized
DSRT errors and never leaks provider or ORM-level exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.api.errors.exceptions import (
    AuthenticationError,
    ConflictError,
    ValidationError,
)
from core.observability.logging import get_logger
from core.repositories import OrganizationRepository, UserRepository
from core.security.passwords import PasswordHasher, get_password_hasher
from core.security.tokens import TokenService, get_token_service
from core.storage.models import Organization, User
from schemas.domain.enums import OrganizationRole


logger = get_logger("dsrt.security.auth")


@dataclass(frozen=True)
class RegistrationResult:
    user: User
    organization: Organization
    access_token: str


@dataclass(frozen=True)
class LoginResult:
    user: User
    access_token: str


class AuthService:
    def __init__(
        self,
        user_repo: UserRepository,
        organization_repo: OrganizationRepository,
        password_hasher: PasswordHasher | None = None,
        token_service: TokenService | None = None,
    ) -> None:
        self._users = user_repo
        self._orgs = organization_repo
        self._hasher = password_hasher or get_password_hasher()
        self._tokens = token_service or get_token_service()

    # --- Registration ---

    async def register_user_with_organization(
        self,
        *,
        email: str,
        display_name: str,
        password: str,
        organization_name: str,
        organization_slug: str,
    ) -> RegistrationResult:
        """Register a new user AND their first organization atomically.

        The registering user becomes the OWNER of the created organization.
        """
        # Pre-flight validation.
        if await self._users.email_exists(email):
            raise ConflictError(
                "A user with this email already exists.",
                metadata={"field": "email"},
            )
        if await self._orgs.slug_exists(organization_slug):
            raise ConflictError(
                "This organization slug is already taken.",
                metadata={"field": "organization_slug"},
            )

        # Hash password.
        try:
            password_hash = self._hasher.hash(password)
        except ValueError as e:
            raise ValidationError(str(e), metadata={"field": "password"}) from e

        # Create user.
        user = await self._users.create(
            email=email,
            display_name=display_name,
            password_hash=password_hash,
        )

        # Create organization.
        organization = await self._orgs.create(
            name=organization_name, slug=organization_slug,
        )

        # Add the user as the organization owner.
        await self._orgs.add_member(
            organization_id=organization.id,
            user_id=user.id,
            role=OrganizationRole.OWNER.value,
        )

        # Issue token.
        access_token, _ = self._tokens.issue_access_token(user_id=user.id)

        logger.info(
            "user_registered",
            user_id=user.id,
            organization_id=organization.id,
        )

        return RegistrationResult(
            user=user, organization=organization, access_token=access_token,
        )

    # --- Login ---

    async def authenticate(self, *, email: str, password: str) -> LoginResult:
        """Verify credentials and issue a token."""
        # Always run bcrypt.verify to avoid timing oracles on user existence.
        user = await self._users.get_by_email(email)

        password_hash = (
            user.password_hash if user else _DUMMY_BCRYPT_HASH
        )
        password_matches = self._hasher.verify(password, password_hash)

        if not user or not password_matches or user.status != "active":
            # Uniform error message regardless of which check failed.
            raise AuthenticationError("Invalid email or password.")

        await self._users.update_last_login(user)

        access_token, _ = self._tokens.issue_access_token(user_id=user.id)

        logger.info("user_logged_in", user_id=user.id)

        return LoginResult(user=user, access_token=access_token)


# A precomputed dummy hash used to keep bcrypt's timing constant even when the
# email lookup fails. This must be a real bcrypt hash for a random password.
_DUMMY_BCRYPT_HASH = (
    "$2b$12$abcdefghijklmnopqrstuuMdN2mCLXfXvHb9zZzAlNqjS4wZGwqLK"
)
