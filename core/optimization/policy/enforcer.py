"""
Policy Enforcement Engine for C11.9.

Validates optimization requests, model selections, strategies, and verifications
against user and organization policies. Enforces tenant isolation and mandatory
security requirements.
"""

from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from schemas.domain.governance import (
    OptimizationPolicy,
    PolicyCheckResult,
    PolicyViolation,
    PolicyEnforcementLevel,
    OptimizationRequest,
)
from core.storage.models.optimization_c11_governance import OptimizationPolicyModel


class PolicyEnforcer:
    """Enforces user and organization optimization policies with tenant isolation."""

    def __init__(self, db_session: Optional[Session] = None):
        self.db_session = db_session

    def get_active_policy(
        self, organization_id: str, user_id: Optional[str] = None
    ) -> Optional[OptimizationPolicy]:
        """
        Retrieves the active policy for a given user/org.
        User-scoped policies take precedence over organization-wide policies.
        """
        if self.db_session is None:
            return None

        # Try user-scoped first
        if user_id:
            user_policy_m = (
                self.db_session.query(OptimizationPolicyModel)
                .filter(
                    OptimizationPolicyModel.organization_id == organization_id,
                    OptimizationPolicyModel.user_id == user_id,
                    OptimizationPolicyModel.active == True,
                )
                .order_by(OptimizationPolicyModel.version.desc())
                .first()
            )
            if user_policy_m:
                return self._model_to_schema(user_policy_m)

        # Fall back to org-wide policy
        org_policy_m = (
            self.db_session.query(OptimizationPolicyModel)
            .filter(
                OptimizationPolicyModel.organization_id == organization_id,
                OptimizationPolicyModel.user_id.is_(None),
                OptimizationPolicyModel.active == True,
            )
            .order_by(OptimizationPolicyModel.version.desc())
            .first()
        )
        if org_policy_m:
            return self._model_to_schema(org_policy_m)

        return None

    def create_default_policy(
        self, organization_id: str, user_id: Optional[str] = None
    ) -> OptimizationPolicy:
        """Creates a default optimization policy for an organization or user."""
        policy = OptimizationPolicy(
            organization_id=organization_id,
            user_id=user_id,
            policy_name=f"Default-{organization_id}" + (f"-{user_id}" if user_id else ""),
        )
        if self.db_session is not None:
            self._persist_policy(policy)
        return policy

    def check_request_compliance(
        self, request: OptimizationRequest, policy: OptimizationPolicy
    ) -> PolicyCheckResult:
        """Validates incoming optimization request against policy."""
        violations: List[PolicyViolation] = []
        approval_required = False

        # 1. Tenant isolation check
        if request.organization_id != policy.organization_id:
            violations.append(
                PolicyViolation(
                    policy_id=policy.policy_id,
                    violation_type="TENANT_ISOLATION_BREACH",
                    severity="critical",
                    message=f"Request org {request.organization_id} does not match policy org {policy.organization_id}",
                )
            )
            return PolicyCheckResult(
                is_compliant=False,
                policy_id=policy.policy_id,
                violations=violations,
                enforcement_level=policy.enforcement_level,
                blocking=True,
            )

        # 2. Model selection lock check
        if policy.model_selection_lock == "fixed" and request.model_preference == "automatic":
            violations.append(
                PolicyViolation(
                    policy_id=policy.policy_id,
                    violation_type="MODEL_LOCK_VIOLATION",
                    severity="error",
                    message="Policy requires fixed model but automatic selection requested",
                )
            )

        # 3. Cost cap check
        if policy.max_cost_usd_per_task is not None and request.max_cost is not None:
            if request.max_cost > policy.max_cost_usd_per_task:
                if policy.approval_required_for_budget_override:
                    approval_required = True
                    violations.append(
                        PolicyViolation(
                            policy_id=policy.policy_id,
                            violation_type="BUDGET_OVERRIDE",
                            severity="warning",
                            requires_approval=True,
                            message=f"Requested cost {request.max_cost} exceeds policy cap {policy.max_cost_usd_per_task}",
                        )
                    )

        # 4. Latency cap check
        if policy.max_latency_ms_per_task is not None and request.max_latency_ms is not None:
            if request.max_latency_ms > policy.max_latency_ms_per_task:
                violations.append(
                    PolicyViolation(
                        policy_id=policy.policy_id,
                        violation_type="LATENCY_CAP_EXCEEDED",
                        severity="warning",
                        message=f"Requested latency {request.max_latency_ms}ms exceeds policy cap",
                    )
                )

        # 5. Escalation / adaptation flag coherence
        if request.allow_model_escalation and not policy.allow_model_escalation:
            violations.append(
                PolicyViolation(
                    policy_id=policy.policy_id,
                    violation_type="ESCALATION_FORBIDDEN",
                    severity="error",
                    message="Policy forbids model escalation but request requested it",
                )
            )

        is_blocking = any(v.severity in ("error", "critical") for v in violations)
        is_compliant = len(violations) == 0

        return PolicyCheckResult(
            is_compliant=is_compliant,
            policy_id=policy.policy_id,
            violations=violations,
            enforcement_level=policy.enforcement_level,
            approval_required=approval_required,
            blocking=is_blocking and policy.enforcement_level in (
                PolicyEnforcementLevel.STRICT,
                PolicyEnforcementLevel.MANDATORY,
            ),
        )

    def check_model_selection_compliance(
        self, model_id: str, policy: OptimizationPolicy
    ) -> PolicyCheckResult:
        """Validates that a specific model selection complies with policy."""
        violations: List[PolicyViolation] = []

        if model_id in policy.forbidden_models:
            violations.append(
                PolicyViolation(
                    policy_id=policy.policy_id,
                    violation_type="FORBIDDEN_MODEL",
                    severity="critical",
                    message=f"Model {model_id} is explicitly forbidden by policy",
                )
            )

        if policy.allowed_models and model_id not in policy.allowed_models:
            violations.append(
                PolicyViolation(
                    policy_id=policy.policy_id,
                    violation_type="MODEL_NOT_ALLOWED",
                    severity="critical",
                    message=f"Model {model_id} is not in allowed models list",
                )
            )

        if (
            policy.model_selection_lock == "fixed"
            and policy.preferred_models
            and model_id not in policy.preferred_models
        ):
            violations.append(
                PolicyViolation(
                    policy_id=policy.policy_id,
                    violation_type="MODEL_LOCK_MISMATCH",
                    severity="critical",
                    message=f"Fixed-model policy requires {policy.preferred_models}, got {model_id}",
                )
            )

        is_blocking = any(v.severity == "critical" for v in violations)

        return PolicyCheckResult(
            is_compliant=len(violations) == 0,
            policy_id=policy.policy_id,
            violations=violations,
            enforcement_level=policy.enforcement_level,
            blocking=is_blocking,
        )

    def _model_to_schema(self, m: OptimizationPolicyModel) -> OptimizationPolicy:
        """Converts ORM model to Pydantic schema."""
        return OptimizationPolicy(
            policy_id=m.policy_id,
            organization_id=m.organization_id,
            user_id=m.user_id,
            policy_name=m.policy_name,
            version=m.version,
            optimization_mode=m.optimization_mode,
            preferred_models=m.preferred_models or [],
            allowed_models=m.allowed_models or [],
            forbidden_models=m.forbidden_models or [],
            model_selection_lock=m.model_selection_lock,
            preferred_agents=m.preferred_agents or [],
            allowed_agents=m.allowed_agents or [],
            max_cost_usd_per_task=m.max_cost_usd_per_task,
            max_latency_ms_per_task=m.max_latency_ms_per_task,
            min_quality_score=m.min_quality_score,
            min_reliability_score=m.min_reliability_score,
            allow_model_escalation=m.allow_model_escalation,
            allow_strategy_adaptation=m.allow_strategy_adaptation,
            require_mandatory_security_checks=m.require_mandatory_security_checks,
            approval_required_for_budget_override=m.approval_required_for_budget_override,
            approval_required_for_model_change=m.approval_required_for_model_change,
            approval_required_for_sensitive_tools=m.approval_required_for_sensitive_tools,
            enforcement_level=PolicyEnforcementLevel(m.enforcement_level),
            created_at=m.created_at,
            updated_at=m.updated_at,
            active=m.active,
        )

    def _persist_policy(self, policy: OptimizationPolicy) -> None:
        """Persists policy to database."""
        if self.db_session is None:
            return

        db_model = OptimizationPolicyModel(
            policy_id=policy.policy_id,
            organization_id=policy.organization_id,
            user_id=policy.user_id,
            policy_name=policy.policy_name,
            version=policy.version,
            optimization_mode=policy.optimization_mode,
            preferred_models=policy.preferred_models,
            allowed_models=policy.allowed_models,
            forbidden_models=policy.forbidden_models,
            model_selection_lock=policy.model_selection_lock,
            preferred_agents=policy.preferred_agents,
            allowed_agents=policy.allowed_agents,
            max_cost_usd_per_task=policy.max_cost_usd_per_task,
            max_latency_ms_per_task=policy.max_latency_ms_per_task,
            min_quality_score=policy.min_quality_score,
            min_reliability_score=policy.min_reliability_score,
            allow_model_escalation=policy.allow_model_escalation,
            allow_strategy_adaptation=policy.allow_strategy_adaptation,
            require_mandatory_security_checks=policy.require_mandatory_security_checks,
            approval_required_for_budget_override=policy.approval_required_for_budget_override,
            approval_required_for_model_change=policy.approval_required_for_model_change,
            approval_required_for_sensitive_tools=policy.approval_required_for_sensitive_tools,
            enforcement_level=policy.enforcement_level.value,
            active=policy.active,
        )
        self.db_session.add(db_model)
        self.db_session.commit()