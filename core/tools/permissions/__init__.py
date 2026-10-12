"""Tool Permission Engine module (C3 §11-15, §48-49, §52)."""

from core.tools.permissions.approval_evaluator import evaluate_approval_requirement
from core.tools.permissions.decision import (
    ToolApprovalRequirement,
    ToolDenialReason,
    ToolPermissionCheck,
    ToolPermissionDecision,
)
from core.tools.permissions.engine import ToolPermissionEngine
from core.tools.permissions.intersection import compute_all_denials
from core.tools.permissions.policies import (
    EnvironmentToolPolicy,
    OrgToolPolicy,
    TaskToolPolicy,
)

__all__ = [
    "EnvironmentToolPolicy",
    "OrgToolPolicy",
    "TaskToolPolicy",
    "ToolApprovalRequirement",
    "ToolDenialReason",
    "ToolPermissionCheck",
    "ToolPermissionDecision",
    "ToolPermissionEngine",
    "compute_all_denials",
    "evaluate_approval_requirement",
]