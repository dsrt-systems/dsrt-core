"""
Approval Requirement Evaluator (C3 §14-15, §48-49).

Deterministic evaluator that determines whether a tool execution
requires human approval based on risk level, side-effect class,
and organizational policy.

Pure logic — no database I/O, no async.
"""

from __future__ import annotations

from schemas.domain.enums import OrganizationRole, SideEffectClass, ToolRiskLevel

from core.tools.permissions.decision import ToolApprovalRequirement


# Risk level ordering for comparison (higher = more dangerous)
_RISK_ORDER: dict[ToolRiskLevel, int] = {
    ToolRiskLevel.LOW: 1,
    ToolRiskLevel.MEDIUM: 2,
    ToolRiskLevel.HIGH: 3,
    ToolRiskLevel.CRITICAL: 4,
}

# Role hierarchy for comparison (higher = more authority)
_ROLE_RANK: dict[OrganizationRole, int] = {
    OrganizationRole.VIEWER: 1,
    OrganizationRole.MEMBER: 2,
    OrganizationRole.ADMIN: 3,
    OrganizationRole.OWNER: 4,
}

# Default mapping: risk_level → minimum approval role (used when no custom threshold)
_DEFAULT_RISK_APPROVAL: dict[ToolRiskLevel, OrganizationRole | None] = {
    ToolRiskLevel.LOW: None,        # No approval needed
    ToolRiskLevel.MEDIUM: None,     # No approval needed (logged)
    ToolRiskLevel.HIGH: OrganizationRole.MEMBER,
    ToolRiskLevel.CRITICAL: OrganizationRole.ADMIN,
}

# Default mapping: side_effect → requires approval
_DEFAULT_SIDEEFFECT_APPROVAL: dict[SideEffectClass, bool] = {
    SideEffectClass.PURE: False,
    SideEffectClass.READ: False,
    SideEffectClass.WRITE: False,        # Configurable per org policy
    SideEffectClass.EXTERNAL_ACTION: True,
    SideEffectClass.IRREVERSIBLE: True,
}


def _resolve_role_for_risk_above_threshold(
    risk_level: ToolRiskLevel,
    threshold: ToolRiskLevel,
) -> OrganizationRole:
    """When a custom org threshold is exceeded, determine the required approval role.

    Policy:
      - If risk >= CRITICAL → ADMIN
      - If risk >= HIGH     → MEMBER
      - Otherwise           → MEMBER (minimum escalation)
    """
    if _RISK_ORDER.get(risk_level, 0) >= _RISK_ORDER[ToolRiskLevel.CRITICAL]:
        return OrganizationRole.ADMIN
    if _RISK_ORDER.get(risk_level, 0) >= _RISK_ORDER[ToolRiskLevel.HIGH]:
        return OrganizationRole.MEMBER
    # LOW or MEDIUM exceeded a custom LOW/MEDIUM threshold → require MEMBER approval
    return OrganizationRole.MEMBER


def evaluate_approval_requirement(
    risk_level: ToolRiskLevel,
    side_effect: SideEffectClass,
    *,
    org_max_risk_without_approval: ToolRiskLevel | None = None,
    org_side_effects_requiring_approval: list[SideEffectClass] | None = None,
    org_requires_approval_for_external: bool | None = None,
    user_role: OrganizationRole | None = None,
) -> ToolApprovalRequirement | None:
    """Determine if a tool execution requires human approval.

    Returns None if no approval is needed.
    Returns a ToolApprovalRequirement if approval IS needed.

    Logic:
        1. Check risk-level threshold (custom or default).
        2. Check side-effect class.
        3. If EITHER triggers approval, return the stricter requirement.
        4. If the user's role already meets or exceeds the required role,
           approval is NOT needed (the user IS the approver).
    """

    # --- 1. Risk-level check ---
    risk_approval_role: OrganizationRole | None = None

    if org_max_risk_without_approval is not None:
        # Custom org threshold — if exceeded, require approval
        tool_rank = _RISK_ORDER.get(risk_level, 0)
        threshold_rank = _RISK_ORDER.get(org_max_risk_without_approval, 4)
        if tool_rank > threshold_rank:
            risk_approval_role = _resolve_role_for_risk_above_threshold(
                risk_level, org_max_risk_without_approval,
            )
    else:
        # Default mapping
        risk_approval_role = _DEFAULT_RISK_APPROVAL.get(risk_level)

    # --- 2. Side-effect check ---
    side_effect_needs_approval = False

    if org_side_effects_requiring_approval is not None:
        side_effect_needs_approval = side_effect in org_side_effects_requiring_approval
    else:
        side_effect_needs_approval = _DEFAULT_SIDEEFFECT_APPROVAL.get(side_effect, False)

    if org_requires_approval_for_external is not None:
        if side_effect == SideEffectClass.EXTERNAL_ACTION:
            side_effect_needs_approval = org_requires_approval_for_external

    # --- 3. Combine ---
    if not risk_approval_role and not side_effect_needs_approval:
        return None  # No approval needed

    # Determine the required role (take the stricter of the two)
    required_role = risk_approval_role or OrganizationRole.MEMBER

    if side_effect_needs_approval and side_effect == SideEffectClass.IRREVERSIBLE:
        # Irreversible actions always require at least ADMIN
        if _ROLE_RANK.get(required_role, 0) < _ROLE_RANK[OrganizationRole.ADMIN]:
            required_role = OrganizationRole.ADMIN

    # --- 4. Self-approval check ---
    if user_role is not None:
        if _ROLE_RANK.get(user_role, 0) >= _ROLE_RANK.get(required_role, 0):
            return None  # User's role is sufficient — no separate approval needed

    # --- 5. Build requirement ---
    reason_parts: list[str] = []
    if risk_approval_role:
        reason_parts.append(f"Risk level {risk_level.value} requires approval")
    if side_effect_needs_approval:
        reason_parts.append(f"Side-effect {side_effect.value} requires approval")

    return ToolApprovalRequirement(
        required_role=required_role,
        reason="; ".join(reason_parts),
        risk_level=risk_level,
        side_effect=side_effect,
        expires_in_seconds=300,
    )