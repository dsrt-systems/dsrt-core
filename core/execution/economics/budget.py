"""
BudgetEnforcer — multi-level pre-operation budget gates.

Enforcement points (spec §8):
- Before starting a run
- Before each model invocation
- Before expensive tool execution
- Before retries and repairs
- Before model escalation
- During long-running execution
"""

from __future__ import annotations

import logging

from core.execution.economics.contracts import (
    BudgetCheckResult,
    BudgetDecision,
    BudgetDefinition,
    BudgetScope,
    CostCategory,
)
from core.execution.economics.ledger import CostLedger

logger = logging.getLogger(__name__)


class BudgetExceededError(Exception):
    """Raised when a hard budget limit would be exceeded."""

    def __init__(self, check: BudgetCheckResult) -> None:
        self.check = check
        super().__init__(check.reason or "Budget exceeded")


class BudgetEnforcer:
    """
    Checks projected spend against registered budgets.

    Does not record costs — only gates operations. The caller records
    the actual cost in the ledger after the operation succeeds/fails.
    """

    def __init__(self, ledger: CostLedger) -> None:
        self._ledger = ledger
        self._budgets: dict[str, BudgetDefinition] = {}

    def register(self, budget: BudgetDefinition) -> BudgetDefinition:
        if budget.limit_usd < 0:
            raise ValueError("Budget limit_usd cannot be negative")
        if not 0.0 < budget.warn_threshold_ratio <= 1.0:
            raise ValueError("warn_threshold_ratio must be in (0, 1]")
        self._budgets[budget.budget_id] = budget
        return budget

    def get(self, budget_id: str) -> BudgetDefinition | None:
        return self._budgets.get(budget_id)

    def list_for_scope(self, scope: BudgetScope, scope_id: str) -> list[BudgetDefinition]:
        return [
            b for b in self._budgets.values()
            if b.scope == scope and b.scope_id == scope_id
        ]

    def check(
        self,
        *,
        budget: BudgetDefinition,
        pending_usd: float,
        category: CostCategory | None = None,
        operation: str = "",
    ) -> BudgetCheckResult:
        """
        Evaluate whether ``pending_usd`` may proceed under ``budget``.
        """
        if pending_usd < 0:
            raise ValueError("pending_usd cannot be negative")

        spent = self._spent_for_budget(budget)
        projected = spent + pending_usd
        remaining = max(0.0, budget.limit_usd - spent)
        warn_at = budget.limit_usd * budget.warn_threshold_ratio

        # Per-operation caps
        if (
            category == CostCategory.MODEL_INFERENCE
            and budget.max_single_model_call_usd is not None
            and pending_usd > budget.max_single_model_call_usd
        ):
            return BudgetCheckResult(
                decision=BudgetDecision.DENY,
                budget_id=budget.budget_id,
                scope=budget.scope,
                limit_usd=budget.limit_usd,
                spent_usd=spent,
                pending_usd=pending_usd,
                projected_usd=projected,
                remaining_usd=remaining,
                warn_threshold_usd=warn_at,
                reason=(
                    f"Single model call ${pending_usd:.6f} exceeds per-call cap "
                    f"${budget.max_single_model_call_usd:.6f}."
                ),
                category=category,
                operation=operation,
            )

        if (
            category == CostCategory.TOOLS
            and budget.max_single_tool_call_usd is not None
            and pending_usd > budget.max_single_tool_call_usd
        ):
            return BudgetCheckResult(
                decision=BudgetDecision.DENY,
                budget_id=budget.budget_id,
                scope=budget.scope,
                limit_usd=budget.limit_usd,
                spent_usd=spent,
                pending_usd=pending_usd,
                projected_usd=projected,
                remaining_usd=remaining,
                warn_threshold_usd=warn_at,
                reason=(
                    f"Single tool call ${pending_usd:.6f} exceeds per-call cap "
                    f"${budget.max_single_tool_call_usd:.6f}."
                ),
                category=category,
                operation=operation,
            )

        if (
            category == CostCategory.RECOVERY
            and budget.max_repair_usd is not None
            and pending_usd > budget.max_repair_usd
        ):
            return BudgetCheckResult(
                decision=BudgetDecision.DENY,
                budget_id=budget.budget_id,
                scope=budget.scope,
                limit_usd=budget.limit_usd,
                spent_usd=spent,
                pending_usd=pending_usd,
                projected_usd=projected,
                remaining_usd=remaining,
                warn_threshold_usd=warn_at,
                reason=(
                    f"Repair cost ${pending_usd:.6f} exceeds repair cap "
                    f"${budget.max_repair_usd:.6f}."
                ),
                category=category,
                operation=operation,
            )

        # Hard limit
        if projected > budget.limit_usd + 1e-12:
            decision = (
                BudgetDecision.DENY if budget.hard_limit else BudgetDecision.WARN
            )
            return BudgetCheckResult(
                decision=decision,
                budget_id=budget.budget_id,
                scope=budget.scope,
                limit_usd=budget.limit_usd,
                spent_usd=spent,
                pending_usd=pending_usd,
                projected_usd=projected,
                remaining_usd=remaining,
                warn_threshold_usd=warn_at,
                reason=(
                    f"Projected spend ${projected:.6f} exceeds budget "
                    f"${budget.limit_usd:.6f} "
                    f"(spent ${spent:.6f} + pending ${pending_usd:.6f})."
                ),
                category=category,
                operation=operation,
            )

        # Warn threshold
        if projected >= warn_at:
            return BudgetCheckResult(
                decision=BudgetDecision.WARN,
                budget_id=budget.budget_id,
                scope=budget.scope,
                limit_usd=budget.limit_usd,
                spent_usd=spent,
                pending_usd=pending_usd,
                projected_usd=projected,
                remaining_usd=max(0.0, budget.limit_usd - projected),
                warn_threshold_usd=warn_at,
                reason=(
                    f"Projected spend ${projected:.6f} reached warn threshold "
                    f"${warn_at:.6f} ({budget.warn_threshold_ratio:.0%} of "
                    f"${budget.limit_usd:.6f})."
                ),
                category=category,
                operation=operation,
            )

        return BudgetCheckResult(
            decision=BudgetDecision.ALLOW,
            budget_id=budget.budget_id,
            scope=budget.scope,
            limit_usd=budget.limit_usd,
            spent_usd=spent,
            pending_usd=pending_usd,
            projected_usd=projected,
            remaining_usd=max(0.0, budget.limit_usd - projected),
            warn_threshold_usd=warn_at,
            reason="Within budget.",
            category=category,
            operation=operation,
        )

    def authorize_or_raise(
        self,
        *,
        budget: BudgetDefinition,
        pending_usd: float,
        category: CostCategory | None = None,
        operation: str = "",
    ) -> BudgetCheckResult:
        """Check and raise BudgetExceededError on DENY."""
        result = self.check(
            budget=budget,
            pending_usd=pending_usd,
            category=category,
            operation=operation,
        )
        if result.decision == BudgetDecision.DENY:
            logger.warning("Budget DENY: %s", result.reason)
            raise BudgetExceededError(result)
        if result.decision == BudgetDecision.WARN:
            logger.info("Budget WARN: %s", result.reason)
        return result

    def authorize_all(
        self,
        *,
        budgets: list[BudgetDefinition],
        pending_usd: float,
        category: CostCategory | None = None,
        operation: str = "",
        raise_on_deny: bool = True,
    ) -> list[BudgetCheckResult]:
        """
        Check multiple budgets (e.g. execution + experiment + workspace).
        DENY from any hard budget blocks the operation.
        """
        results: list[BudgetCheckResult] = []
        for b in budgets:
            if raise_on_deny:
                results.append(
                    self.authorize_or_raise(
                        budget=b,
                        pending_usd=pending_usd,
                        category=category,
                        operation=operation,
                    )
                )
            else:
                results.append(
                    self.check(
                        budget=b,
                        pending_usd=pending_usd,
                        category=category,
                        operation=operation,
                    )
                )
        return results

    def _spent_for_budget(self, budget: BudgetDefinition) -> float:
        include_est = budget.allow_estimated_enforcement
        if budget.scope == BudgetScope.EXECUTION:
            return self._ledger.spent_usd(
                execution_id=budget.scope_id,
                include_estimated=include_est,
            )
        if budget.scope == BudgetScope.EXPERIMENT:
            return self._ledger.spent_usd(
                experiment_id=budget.scope_id,
                include_estimated=include_est,
            )
        if budget.scope == BudgetScope.WORKSPACE:
            return self._ledger.spent_usd(
                workspace_id=budget.scope_id,
                include_estimated=include_est,
            )
        # OPERATION scope has no cumulative spend — only per-call caps apply
        return 0.0