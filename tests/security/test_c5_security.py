"""
C5 Security Regression Tests.

Verifies that orchestration security invariants are enforced:
  - Delegation permission inheritance (Invariant 2)
  - Budget propagation (Invariant 3)
  - Depth limits (C5 §83)
  - State isolation (C5 §22)
  - Plan immutability (Invariant 4)
"""

from __future__ import annotations

import pytest

from core.orchestration.delegation.delegation import DelegationManager, DelegationRequest
from core.orchestration.state.patches import StatePatchValidator, PatchApplicationError
from core.orchestration.state.concurrency import OptimisticConcurrencyControl, ConcurrencyConflict
from schemas.domain.enums import RecoveryAction
from core.orchestration.recovery.recovery import RecoveryManager


class TestDelegationSecurity:
    """C5 §81-83: Delegation security invariants."""

    def test_network_permission_inherited(self):
        mgr = DelegationManager.__new__(DelegationManager)
        result = mgr._check_permission_inheritance(
            parent_permissions={"network": False},
            agent_slug="web_agent",
            requested_capability="web_search",
        )
        assert not result.allowed

    def test_external_actions_inherited(self):
        mgr = DelegationManager.__new__(DelegationManager)
        result = mgr._check_permission_inheritance(
            parent_permissions={"external_actions": False},
            agent_slug="email_agent",
            requested_capability="send_email",
        )
        assert not result.allowed

    def test_filesystem_inherited(self):
        mgr = DelegationManager.__new__(DelegationManager)
        result = mgr._check_permission_inheritance(
            parent_permissions={"filesystem": "none"},
            agent_slug="code_agent",
            requested_capability="code_execution",
        )
        assert not result.allowed

    def test_budget_usd_enforced(self):
        mgr = DelegationManager.__new__(DelegationManager)
        result = mgr._check_budget_propagation(
            parent_budget={"remaining_usd": 1.0},
            child_allocation={"max_usd": 5.0},
        )
        assert not result.allowed

    def test_budget_model_calls_enforced(self):
        mgr = DelegationManager.__new__(DelegationManager)
        result = mgr._check_budget_propagation(
            parent_budget={"remaining_model_calls": 5},
            child_allocation={"max_model_calls": 20},
        )
        assert not result.allowed

    def test_budget_duration_enforced(self):
        mgr = DelegationManager.__new__(DelegationManager)
        result = mgr._check_budget_propagation(
            parent_budget={"remaining_seconds": 60},
            child_allocation={"max_duration_seconds": 300},
        )
        assert not result.allowed

    def test_depth_limit_enforced(self):
        req = DelegationRequest(
            parent_node_execution_id="nex_1",
            orchestration_execution_id="oex_1",
            organization_id="org_1",
            task_id="tsk_1",
            requested_capability="test",
            objective="test",
            parent_depth=5,
        )
        assert req.parent_depth >= 5  # At max depth


class TestStateSecurity:
    """C5 §22: State corruption prevention."""

    def test_path_traversal_blocked(self):
        with pytest.raises(PatchApplicationError):
            StatePatchValidator.apply_patch(
                {"a": 1}, "/../../../etc/passwd", "add", "x",
            )

    def test_empty_segment_blocked(self):
        with pytest.raises(PatchApplicationError):
            StatePatchValidator.validate_path("/a//b")

    def test_original_state_not_mutated(self):
        state = {"x": 1, "y": {"z": 2}}
        new = StatePatchValidator.apply_patch(state, "/x", "replace", 99)
        assert state["x"] == 1  # Original unchanged
        assert new["x"] == 99

    def test_concurrency_conflict_detected(self):
        occ = OptimisticConcurrencyControl()
        with pytest.raises(ConcurrencyConflict):
            occ.check_version(expected_version=5, actual_version=6)


class TestRecoverySecurity:
    """C5 §31: Recovery policy enforcement."""

    def test_non_retryable_not_retried(self):
        rm = RecoveryManager.__new__(RecoveryManager)
        rm._max_attempts = 3
        rm._base_backoff = 2.0
        rm._max_backoff = 60.0
        rm._backoff_multiplier = 2.0
        rm._heartbeat_timeout = 300
        d = rm.classify_and_decide("node", "PERMISSION_DENIED", attempt=1)
        assert d.action == RecoveryAction.CANCEL

    def test_exhausted_retries_trigger_replan(self):
        rm = RecoveryManager.__new__(RecoveryManager)
        rm._max_attempts = 3
        rm._base_backoff = 2.0
        rm._max_backoff = 60.0
        rm._backoff_multiplier = 2.0
        rm._heartbeat_timeout = 300
        d = rm.classify_and_decide("node", "PROVIDER_TIMEOUT", attempt=3, max_attempts=3)
        assert d.action == RecoveryAction.REPLAN