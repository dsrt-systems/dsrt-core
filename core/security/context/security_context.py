"""
SecurityContext — the immutable identity object flowing through DSRT.

Every authenticated operation receives a SecurityContext. Downstream services
NEVER trust identity data from anywhere else (headers, URL params, body).

Tenant scope is derived from authenticated membership, not client input.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from schemas.domain.enums import OrganizationRole


@dataclass(frozen=True)
class OrganizationMembership:
    organization_id: str
    role: OrganizationRole


@dataclass(frozen=True)
class SecurityContext:
    """The identity and authorization envelope of an authenticated request."""

    user_id: str
    email: str
    display_name: str

    # All organizations the user is a member of.
    memberships: tuple[OrganizationMembership, ...] = field(default_factory=tuple)

    # The currently ACTIVE organization for this request (if selected).
    # Derived from the request header X-DSRT-Organization or a single-membership fallback.
    active_organization_id: str | None = None

    # jti of the access token used for this request (for future revocation).
    token_jti: str | None = None

    # --- Derived helpers ---

    def is_member_of(self, organization_id: str) -> bool:
        return any(m.organization_id == organization_id for m in self.memberships)

    def role_in(self, organization_id: str) -> OrganizationRole | None:
        for m in self.memberships:
            if m.organization_id == organization_id:
                return m.role
        return None

    def has_role(
        self, organization_id: str, minimum_role: OrganizationRole,
    ) -> bool:
        role = self.role_in(organization_id)
        if role is None:
            return False
        return _ROLE_RANK[role] >= _ROLE_RANK[minimum_role]

    def active_role(self) -> OrganizationRole | None:
        if self.active_organization_id is None:
            return None
        return self.role_in(self.active_organization_id)


# Role hierarchy — higher rank = more permissions.
_ROLE_RANK: dict[OrganizationRole, int] = {
    OrganizationRole.VIEWER: 1,
    OrganizationRole.MEMBER: 2,
    OrganizationRole.ADMIN: 3,
    OrganizationRole.OWNER: 4,
}
