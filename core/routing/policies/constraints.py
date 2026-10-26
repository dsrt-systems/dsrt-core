# core/routing/policies/constraints.py
"""
C9 Hard Constraint Checkers (§14, §22).

Each checker evaluates one hard constraint against a RouteCandidate.
If the constraint is violated, the candidate is rejected with a
structured reason.  Hard constraints are binary — pass or reject.
"""

from __future__ import annotations

from core.routing.contracts import (
    RouteCandidate,
    RoutingConstraints,
    TaskRequirements,
)
from core.routing.enums import RejectionCategory


class HardConstraintChecker:
    """Evaluates all hard constraints against a candidate (§14)."""

    def check_all(
        self,
        candidate: RouteCandidate,
        constraints: RoutingConstraints,
        requirements: TaskRequirements,
    ) -> bool:
        """Run all hard constraint checks.

        Returns ``True`` if the candidate passes all checks.
        Mutates ``candidate`` by calling ``candidate.reject(...)``
        for each violation.
        """
        passed = True

        if not self._check_model_allowed(candidate, constraints):
            passed = False
        if not self._check_agent_allowed(candidate, constraints):
            passed = False
        if not self._check_provider_allowed(candidate, constraints):
            passed = False
        if not self._check_external_write(candidate, constraints, requirements):
            passed = False
        if not self._check_budget(candidate, constraints, requirements):
            passed = False
        if not self._check_latency(candidate, constraints):
            passed = False
        if not self._check_security(candidate, requirements):
            passed = False
        if not self._check_constraint_fit(candidate):
            passed = False

        return passed

    # ── Individual checkers ───────────────────────────────────────

    def _check_model_allowed(
        self, candidate: RouteCandidate, constraints: RoutingConstraints
    ) -> bool:
        if not constraints.is_model_allowed(candidate.model_id):
            candidate.reject(
                RejectionCategory.POLICY_DENIED,
                f"Model '{candidate.model_id}' not allowed by policy",
                constraint_ref="constraints.allowed_models",
            )
            return False
        return True

    def _check_agent_allowed(
        self, candidate: RouteCandidate, constraints: RoutingConstraints
    ) -> bool:
        if not constraints.is_agent_allowed(candidate.agent_id):
            candidate.reject(
                RejectionCategory.POLICY_DENIED,
                f"Agent '{candidate.agent_id}' not allowed by policy",
                constraint_ref="constraints.allowed_agents",
            )
            return False
        return True

    def _check_provider_allowed(
        self, candidate: RouteCandidate, constraints: RoutingConstraints
    ) -> bool:
        if not constraints.is_provider_allowed(candidate.provider_id):
            candidate.reject(
                RejectionCategory.POLICY_DENIED,
                f"Provider '{candidate.provider_id}' not allowed by policy",
                constraint_ref="constraints.allowed_providers",
            )
            return False
        return True

    def _check_external_write(
        self,
        candidate: RouteCandidate,
        constraints: RoutingConstraints,
        requirements: TaskRequirements,
    ) -> bool:
        """Policy forbids external writes but task requires them."""
        if (
            not constraints.external_write_actions
            and requirements.security.external_write_actions
        ):
            candidate.reject(
                RejectionCategory.SECURITY_VIOLATION,
                "Task requires external write actions but policy forbids them",
                constraint_ref="constraints.external_write_actions",
            )
            return False
        return True

    def _check_budget(
        self,
        candidate: RouteCandidate,
        constraints: RoutingConstraints,
        requirements: TaskRequirements,
    ) -> bool:
        """Policy budget ceiling vs task budget."""
        policy_max = constraints.max_cost_usd
        task_max = requirements.resources.max_cost_usd

        if policy_max is not None and task_max is not None:
            if task_max > policy_max:
                candidate.reject(
                    RejectionCategory.BUDGET_EXCEEDED,
                    f"Task budget ${task_max} exceeds policy ceiling ${policy_max}",
                    constraint_ref="constraints.max_cost_usd",
                )
                return False
        return True

    def _check_latency(
        self,
        candidate: RouteCandidate,
        constraints: RoutingConstraints,
    ) -> bool:
        """Policy latency ceiling (checked against constraint_fit)."""
        if constraints.max_latency_seconds is not None:
            # Latency is estimated later; here we just note the constraint
            candidate.constraint_fit["latency_within_policy"] = True
        return True

    def _check_security(
        self,
        candidate: RouteCandidate,
        requirements: TaskRequirements,
    ) -> bool:
        """Task security requirements vs candidate capabilities."""
        if requirements.security.requires_sandbox:
            # Sandbox requirement is a world-level concern; if the
            # candidate has no world, it cannot satisfy sandbox.
            if candidate.world_id is None:
                candidate.reject(
                    RejectionCategory.SECURITY_VIOLATION,
                    "Task requires sandboxed execution but no world selected",
                    constraint_ref="security.requires_sandbox",
                )
                return False
        return True

    def _check_constraint_fit(self, candidate: RouteCandidate) -> bool:
        """Check pre-computed constraint_fit flags from CandidateGenerator."""
        for key, value in candidate.constraint_fit.items():
            if value is False and key in ("tools_available", "context_window"):
                candidate.reject(
                    RejectionCategory.MISSING_CAPABILITY,
                    f"Constraint '{key}' not satisfied",
                    constraint_ref=f"constraint_fit.{key}",
                )
                return False
        return True