"""Unit tests for approval requirement evaluator (C3 §14-15, §48-49)."""

from __future__ import annotations

import pytest

from schemas.domain.enums import OrganizationRole, SideEffectClass, ToolRiskLevel

from core.tools.permissions.approval_evaluator import evaluate_approval_requirement


class TestApprovalEvaluator:
    def test_low_risk_read_no_approval(self):
        result = evaluate_approval_requirement(
            risk_level=ToolRiskLevel.LOW,
            side_effect=SideEffectClass.READ,
        )
        assert result is None

    def test_medium_risk_write_no_approval(self):
        result = evaluate_approval_requirement(
            risk_level=ToolRiskLevel.MEDIUM,
            side_effect=SideEffectClass.WRITE,
        )
        assert result is None

    def test_high_risk_requires_approval(self):
        result = evaluate_approval_requirement(
            risk_level=ToolRiskLevel.HIGH,
            side_effect=SideEffectClass.READ,
        )
        assert result is not None
        assert result.required_role == OrganizationRole.MEMBER

    def test_critical_risk_requires_admin(self):
        result = evaluate_approval_requirement(
            risk_level=ToolRiskLevel.CRITICAL,
            side_effect=SideEffectClass.READ,
        )
        assert result is not None
        assert result.required_role == OrganizationRole.ADMIN

    def test_external_action_requires_approval(self):
        result = evaluate_approval_requirement(
            risk_level=ToolRiskLevel.LOW,
            side_effect=SideEffectClass.EXTERNAL_ACTION,
        )
        assert result is not None

    def test_irreversible_requires_admin(self):
        result = evaluate_approval_requirement(
            risk_level=ToolRiskLevel.LOW,
            side_effect=SideEffectClass.IRREVERSIBLE,
        )
        assert result is not None
        assert result.required_role == OrganizationRole.ADMIN

    def test_owner_self_approves_high_risk(self):
        result = evaluate_approval_requirement(
            risk_level=ToolRiskLevel.HIGH,
            side_effect=SideEffectClass.READ,
            user_role=OrganizationRole.OWNER,
        )
        assert result is None  # Owner's role >= MEMBER, so no separate approval

    def test_viewer_cannot_self_approve(self):
        result = evaluate_approval_requirement(
            risk_level=ToolRiskLevel.HIGH,
            side_effect=SideEffectClass.READ,
            user_role=OrganizationRole.VIEWER,
        )
        assert result is not None
        assert result.required_role == OrganizationRole.MEMBER

    def test_custom_org_threshold(self):
        result = evaluate_approval_requirement(
            risk_level=ToolRiskLevel.MEDIUM,
            side_effect=SideEffectClass.READ,
            org_max_risk_without_approval=ToolRiskLevel.LOW,
        )
        assert result is not None  # MEDIUM exceeds LOW threshold

    def test_custom_side_effect_list(self):
        result = evaluate_approval_requirement(
            risk_level=ToolRiskLevel.LOW,
            side_effect=SideEffectClass.WRITE,
            org_side_effects_requiring_approval=[SideEffectClass.WRITE],
        )
        assert result is not None

    def test_external_approval_disabled_by_org(self):
        result = evaluate_approval_requirement(
            risk_level=ToolRiskLevel.LOW,
            side_effect=SideEffectClass.EXTERNAL_ACTION,
            org_requires_approval_for_external=False,
        )
        assert result is None