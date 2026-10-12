"""Unit tests for Memory Permission Engine (C4 §7, §8, §33-34)."""

from __future__ import annotations

import pytest

from schemas.domain.enums import MemoryScope

from core.memory.permissions.engine import (
    MemoryAccessDecision,
    MemoryAction,
    MemoryDenialReason,
    MemoryPermissionEngine,
)
from core.memory.permissions.policies import MemoryAccessPolicy, MemoryScopePolicy


class TestOrganizationBoundary:
    """C4 §65: Cross-organization retrieval must be DENIED."""

    def test_cross_org_read_denied(self):
        engine = MemoryPermissionEngine()
        decision = engine.authorize(
            action=MemoryAction.READ,
            requester_org_id="org_A",
            memory_org_id="org_B",
            scope=MemoryScope.PROJECT,
        )
        assert decision.allowed is False
        assert decision.denial_reason == MemoryDenialReason.ORGANIZATION_MISMATCH

    def test_cross_org_write_denied(self):
        engine = MemoryPermissionEngine()
        decision = engine.authorize(
            action=MemoryAction.WRITE,
            requester_org_id="org_A",
            memory_org_id="org_B",
            scope=MemoryScope.PROJECT,
        )
        assert decision.allowed is False
        assert decision.denial_reason == MemoryDenialReason.ORGANIZATION_MISMATCH

    def test_same_org_read_allowed(self):
        engine = MemoryPermissionEngine()
        decision = engine.authorize(
            action=MemoryAction.READ,
            requester_org_id="org_A",
            memory_org_id="org_A",
            scope=MemoryScope.PROJECT,
        )
        assert decision.allowed is True


class TestScopeAccess:
    """C4 §7: Memory scope governs visibility."""

    def test_default_policy_allows_task_read(self):
        engine = MemoryPermissionEngine()
        decision = engine.authorize(
            action=MemoryAction.READ,
            requester_org_id="org_A",
            memory_org_id="org_A",
            scope=MemoryScope.TASK,
        )
        assert decision.allowed is True

    def test_default_policy_allows_project_write(self):
        engine = MemoryPermissionEngine()
        decision = engine.authorize(
            action=MemoryAction.WRITE,
            requester_org_id="org_A",
            memory_org_id="org_A",
            scope=MemoryScope.PROJECT,
        )
        assert decision.allowed is True

    def test_default_policy_denies_org_read(self):
        """Default agent policy doesn't include ORGANIZATION in readable scopes."""
        engine = MemoryPermissionEngine()
        decision = engine.authorize(
            action=MemoryAction.READ,
            requester_org_id="org_A",
            memory_org_id="org_A",
            scope=MemoryScope.ORGANIZATION,
        )
        assert decision.allowed is False
        assert decision.denial_reason == MemoryDenialReason.SCOPE_NOT_READABLE

    def test_custom_policy_allows_org_read(self):
        """An agent with explicit org-read permission can read org memories."""
        agent_policy = MemoryAccessPolicy(
            readable_scopes=[MemoryScope.TASK, MemoryScope.PROJECT, MemoryScope.ORGANIZATION],
            writable_scopes=[MemoryScope.TASK, MemoryScope.PROJECT],
        )
        engine = MemoryPermissionEngine(agent_policy=agent_policy)
        decision = engine.authorize(
            action=MemoryAction.READ,
            requester_org_id="org_A",
            memory_org_id="org_A",
            scope=MemoryScope.ORGANIZATION,
        )
        assert decision.allowed is True

    def test_default_policy_denies_promote(self):
        """Default agent policy has empty promotable_scopes."""
        engine = MemoryPermissionEngine()
        decision = engine.authorize(
            action=MemoryAction.PROMOTE,
            requester_org_id="org_A",
            memory_org_id="org_A",
            scope=MemoryScope.PROJECT,
        )
        assert decision.allowed is False
        assert decision.denial_reason == MemoryDenialReason.SCOPE_NOT_PROMOTABLE

    def test_default_policy_denies_delete(self):
        """Default agent policy has empty deletable_scopes."""
        engine = MemoryPermissionEngine()
        decision = engine.authorize(
            action=MemoryAction.DELETE,
            requester_org_id="org_A",
            memory_org_id="org_A",
            scope=MemoryScope.TASK,
        )
        assert decision.allowed is False
        assert decision.denial_reason == MemoryDenialReason.SCOPE_NOT_DELETABLE


class TestScopeIdMatching:
    """C4 §65: Project boundary enforcement."""

    def test_cross_project_read_denied_by_default(self):
        engine = MemoryPermissionEngine()
        decision = engine.authorize(
            action=MemoryAction.READ,
            requester_org_id="org_A",
            memory_org_id="org_A",
            scope=MemoryScope.PROJECT,
            scope_id="project_X",
            requester_scope_ids=["project_Y"],
        )
        assert decision.allowed is False
        assert decision.denial_reason == MemoryDenialReason.CROSS_PROJECT_DENIED

    def test_same_project_read_allowed(self):
        engine = MemoryPermissionEngine()
        decision = engine.authorize(
            action=MemoryAction.READ,
            requester_org_id="org_A",
            memory_org_id="org_A",
            scope=MemoryScope.PROJECT,
            scope_id="project_X",
            requester_scope_ids=["project_X", "project_Y"],
        )
        assert decision.allowed is True

    def test_cross_project_read_allowed_by_policy(self):
        scope_policy = MemoryScopePolicy(allow_cross_project_read=True)
        engine = MemoryPermissionEngine(scope_policy=scope_policy)
        decision = engine.authorize(
            action=MemoryAction.READ,
            requester_org_id="org_A",
            memory_org_id="org_A",
            scope=MemoryScope.PROJECT,
            scope_id="project_X",
            requester_scope_ids=["project_Y"],
        )
        assert decision.allowed is True


class TestOrgWriteProtection:
    """C4 §34: Organization-scope writes require approval by default."""

    def test_org_write_requires_approval_by_default(self):
        agent_policy = MemoryAccessPolicy(
            writable_scopes=[MemoryScope.ORGANIZATION],
        )
        engine = MemoryPermissionEngine(agent_policy=agent_policy)
        decision = engine.authorize(
            action=MemoryAction.WRITE,
            requester_org_id="org_A",
            memory_org_id="org_A",
            scope=MemoryScope.ORGANIZATION,
        )
        assert decision.allowed is False
        assert decision.denial_reason == MemoryDenialReason.ORG_WRITE_REQUIRES_APPROVAL

    def test_org_write_allowed_when_policy_disabled(self):
        scope_policy = MemoryScopePolicy(require_approval_for_org_write=False)
        agent_policy = MemoryAccessPolicy(
            writable_scopes=[MemoryScope.ORGANIZATION],
        )
        engine = MemoryPermissionEngine(
            scope_policy=scope_policy,
            agent_policy=agent_policy,
        )
        decision = engine.authorize(
            action=MemoryAction.WRITE,
            requester_org_id="org_A",
            memory_org_id="org_A",
            scope=MemoryScope.ORGANIZATION,
        )
        assert decision.allowed is True


class TestDecisionImmutability:
    def test_decision_is_frozen(self):
        decision = MemoryAccessDecision(
            allowed=True,
            action=MemoryAction.READ,
            scope=MemoryScope.PROJECT,
        )
        assert decision.allowed is True
        # Frozen dataclass — cannot mutate
        with pytest.raises(AttributeError):
            decision.allowed = False  # type: ignore[misc]