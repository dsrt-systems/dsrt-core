"""Permission engine unit tests."""

import pytest

from core.api.errors.exceptions import AuthorizationError
from core.security.context import OrganizationMembership, SecurityContext
from core.security.permissions import Action, PermissionCheck, PermissionEngine
from schemas.domain.enums import OrganizationRole


def _ctx(*memberships: tuple[str, OrganizationRole]) -> SecurityContext:
    return SecurityContext(
        user_id="usr_1",
        email="a@b.co",
        display_name="A",
        memberships=tuple(
            OrganizationMembership(organization_id=o, role=r) for o, r in memberships
        ),
    )


class TestPermissionEngine:
    def setup_method(self):
        self.engine = PermissionEngine()

    def test_denies_non_member(self):
        ctx = _ctx(("org_a", OrganizationRole.OWNER))
        with pytest.raises(AuthorizationError):
            self.engine.evaluate(
                ctx,
                PermissionCheck(
                    action=Action.READ_ORGANIZATION,
                    organization_id="org_b",
                ),
            )

    def test_viewer_can_read(self):
        ctx = _ctx(("org_a", OrganizationRole.VIEWER))
        self.engine.evaluate(
            ctx,
            PermissionCheck(
                action=Action.READ_ORGANIZATION, organization_id="org_a",
            ),
        )

    def test_viewer_cannot_create_task(self):
        ctx = _ctx(("org_a", OrganizationRole.VIEWER))
        with pytest.raises(AuthorizationError):
            self.engine.evaluate(
                ctx,
                PermissionCheck(
                    action=Action.CREATE_TASK, organization_id="org_a",
                ),
            )

    def test_member_can_create_task(self):
        ctx = _ctx(("org_a", OrganizationRole.MEMBER))
        self.engine.evaluate(
            ctx,
            PermissionCheck(
                action=Action.CREATE_TASK, organization_id="org_a",
            ),
        )

    def test_admin_can_manage_members(self):
        ctx = _ctx(("org_a", OrganizationRole.ADMIN))
        self.engine.evaluate(
            ctx,
            PermissionCheck(
                action=Action.MANAGE_MEMBERS, organization_id="org_a",
            ),
        )

    def test_admin_cannot_manage_organization(self):
        ctx = _ctx(("org_a", OrganizationRole.ADMIN))
        with pytest.raises(AuthorizationError):
            self.engine.evaluate(
                ctx,
                PermissionCheck(
                    action=Action.MANAGE_ORGANIZATION,
                    organization_id="org_a",
                ),
            )

    def test_owner_can_manage_organization(self):
        ctx = _ctx(("org_a", OrganizationRole.OWNER))
        self.engine.evaluate(
            ctx,
            PermissionCheck(
                action=Action.MANAGE_ORGANIZATION, organization_id="org_a",
            ),
        )


class TestSecurityContext:
    def test_role_hierarchy(self):
        ctx = _ctx(("org_a", OrganizationRole.ADMIN))
        assert ctx.has_role("org_a", OrganizationRole.VIEWER) is True
        assert ctx.has_role("org_a", OrganizationRole.MEMBER) is True
        assert ctx.has_role("org_a", OrganizationRole.ADMIN) is True
        assert ctx.has_role("org_a", OrganizationRole.OWNER) is False

    def test_is_member_of(self):
        ctx = _ctx(("org_a", OrganizationRole.MEMBER))
        assert ctx.is_member_of("org_a") is True
        assert ctx.is_member_of("org_b") is False

    def test_role_in_returns_none_for_non_member(self):
        ctx = _ctx(("org_a", OrganizationRole.MEMBER))
        assert ctx.role_in("org_b") is None
