"""
EconomicsEngine — facade used by Direct/Amplified runtimes and experiments.

Provides:
- record_model_usage / record_tool_usage / record_generic
- pre-flight budget authorization
- summaries and path comparisons
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from core.execution.economics.budget import BudgetEnforcer, BudgetExceededError
from core.execution.economics.calculations import CostCalculator, CostComparisonResult
from core.execution.economics.contracts import (
    BudgetCheckResult,
    BudgetDefinition,
    BudgetScope,
    CostAvailability,
    CostBreakdown,
    CostCategory,
    CostEntry,
    EconomicsSummary,
)
from core.execution.economics.ledger import CostLedger
from core.execution.economics.pricing import PricingDirectory, PricingSnapshot

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Requests / reports
# ---------------------------------------------------------------------------

class RecordUsageRequest(BaseModel):
    """Common input for recording usage-derived cost."""

    execution_id: str
    workspace_id: str
    experiment_id: str | None = None
    run_id: str | None = None
    step_id: str | None = None

    category: CostCategory = CostCategory.MODEL_INFERENCE
    operation: str = ""
    description: str = ""

    # Model usage
    provider: str | None = None
    model_id: str | None = None
    model_fingerprint_hash: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0

    # Explicit dollar amount from provider (preferred when present)
    actual_cost_usd: float | None = None

    # Tool / generic
    tool_name: str | None = None
    quantity: float = 1.0
    unit_label: str | None = None

    # Environment
    duration_minutes: float | None = None

    is_retry: bool = False
    is_repair: bool = False
    idempotency_key: str | None = None
    pricing_snapshot_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EconomicsReport(BaseModel):
    """Full economics package for one execution or experiment."""

    report_id: str = Field(default_factory=lambda: str(uuid4()))
    subject_type: str
    subject_id: str
    breakdown: CostBreakdown
    summary: EconomicsSummary
    entries: list[CostEntry] = Field(default_factory=list)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class EconomicsEngine:
    """
    Single entry point for cost recording, budget gates, and reporting.
    """

    def __init__(
        self,
        *,
        ledger: CostLedger | None = None,
        pricing: PricingDirectory | None = None,
        enforcer: BudgetEnforcer | None = None,
        calculator: CostCalculator | None = None,
    ) -> None:
        self.ledger = ledger or CostLedger()
        self.pricing = pricing or PricingDirectory()
        self.enforcer = enforcer or BudgetEnforcer(self.ledger)
        self.calculator = calculator or CostCalculator(self.ledger)
        self._default_snapshot_id: str | None = None

    # -- pricing setup ------------------------------------------------------

    async def set_pricing_snapshot(self, snapshot: PricingSnapshot) -> PricingSnapshot:
        saved = await self.pricing.register(snapshot)
        self._default_snapshot_id = saved.snapshot_id
        return saved

    # -- budget setup -------------------------------------------------------

    def register_budget(self, budget: BudgetDefinition) -> BudgetDefinition:
        return self.enforcer.register(budget)

    def register_execution_budget(
        self,
        *,
        execution_id: str,
        limit_usd: float,
        warn_threshold_ratio: float = 0.8,
        hard_limit: bool = True,
        **kwargs: Any,
    ) -> BudgetDefinition:
        return self.register_budget(
            BudgetDefinition(
                scope=BudgetScope.EXECUTION,
                scope_id=execution_id,
                limit_usd=limit_usd,
                warn_threshold_ratio=warn_threshold_ratio,
                hard_limit=hard_limit,
                **kwargs,
            )
        )

    def register_experiment_budget(
        self,
        *,
        experiment_id: str,
        limit_usd: float,
        **kwargs: Any,
    ) -> BudgetDefinition:
        return self.register_budget(
            BudgetDefinition(
                scope=BudgetScope.EXPERIMENT,
                scope_id=experiment_id,
                limit_usd=limit_usd,
                **kwargs,
            )
        )

    # -- authorize before costly ops ----------------------------------------

    def authorize(
        self,
        *,
        pending_usd: float,
        execution_id: str | None = None,
        experiment_id: str | None = None,
        workspace_id: str | None = None,
        category: CostCategory | None = None,
        operation: str = "",
        raise_on_deny: bool = True,
    ) -> list[BudgetCheckResult]:
        """
        Gate an operation against all applicable registered budgets.
        """
        budgets: list[BudgetDefinition] = []
        if execution_id:
            budgets.extend(
                self.enforcer.list_for_scope(BudgetScope.EXECUTION, execution_id)
            )
        if experiment_id:
            budgets.extend(
                self.enforcer.list_for_scope(BudgetScope.EXPERIMENT, experiment_id)
            )
        if workspace_id:
            budgets.extend(
                self.enforcer.list_for_scope(BudgetScope.WORKSPACE, workspace_id)
            )

        if not budgets:
            # No budget registered → allow (caller may still track cost)
            return []

        return self.enforcer.authorize_all(
            budgets=budgets,
            pending_usd=pending_usd,
            category=category,
            operation=operation,
            raise_on_deny=raise_on_deny,
        )

    # -- record costs -------------------------------------------------------

    async def record_usage(self, request: RecordUsageRequest) -> CostEntry:
        """
        Record a cost entry from usage.

        Preference order for amount:
        1. actual_cost_usd from provider → ACTUAL
        2. estimate from pricing snapshot → ESTIMATED
        3. otherwise → UNAVAILABLE
        """
        snapshot_id = request.pricing_snapshot_id or self._default_snapshot_id
        amount: float | None = None
        availability = CostAvailability.UNAVAILABLE
        meta = dict(request.metadata)

        if request.actual_cost_usd is not None:
            amount = float(request.actual_cost_usd)
            availability = CostAvailability.ACTUAL
        else:
            amount, availability, est_meta = await self._estimate(request, snapshot_id)
            meta.update(est_meta)

        entry = CostEntry(
            execution_id=request.execution_id,
            workspace_id=request.workspace_id,
            experiment_id=request.experiment_id,
            run_id=request.run_id,
            step_id=request.step_id,
            category=request.category,
            availability=availability,
            amount_usd=amount,
            input_tokens=request.input_tokens,
            output_tokens=request.output_tokens,
            cached_tokens=request.cached_tokens,
            quantity=request.quantity,
            unit_label=request.unit_label or (
                "tokens" if request.category in (
                    CostCategory.MODEL_INFERENCE,
                    CostCategory.HOSTED_INFERENCE,
                    CostCategory.PLANNING,
                    CostCategory.RETRIEVAL,
                ) else None
            ),
            pricing_snapshot_id=snapshot_id,
            provider=request.provider,
            model_id=request.model_id,
            model_fingerprint_hash=request.model_fingerprint_hash,
            operation=request.operation,
            idempotency_key=request.idempotency_key,
            description=request.description,
            is_retry=request.is_retry,
            is_repair=request.is_repair or request.category == CostCategory.RECOVERY,
            metadata=meta,
        )
        return self.ledger.record(entry)

    async def record_model_call(
        self,
        *,
        execution_id: str,
        workspace_id: str,
        provider: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
        actual_cost_usd: float | None = None,
        experiment_id: str | None = None,
        run_id: str | None = None,
        step_id: str | None = None,
        model_fingerprint_hash: str | None = None,
        operation: str = "model.invoke",
        category: CostCategory = CostCategory.MODEL_INFERENCE,
        is_retry: bool = False,
        is_repair: bool = False,
        idempotency_key: str | None = None,
        authorize: bool = True,
        estimated_pending_usd: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CostEntry:
        """
        Convenience path for model invocations with optional pre-auth.
        """
        if authorize:
            pending = estimated_pending_usd
            if pending is None and actual_cost_usd is not None:
                pending = actual_cost_usd
            if pending is None:
                # Best-effort estimate for the gate
                pending = await self._quick_estimate_model(
                    provider=provider,
                    model_id=model_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cached_tokens=cached_tokens,
                )
            if pending is not None:
                self.authorize(
                    pending_usd=pending,
                    execution_id=execution_id,
                    experiment_id=experiment_id,
                    workspace_id=workspace_id,
                    category=category,
                    operation=operation,
                )

        return await self.record_usage(
            RecordUsageRequest(
                execution_id=execution_id,
                workspace_id=workspace_id,
                experiment_id=experiment_id,
                run_id=run_id,
                step_id=step_id,
                category=category,
                operation=operation,
                provider=provider,
                model_id=model_id,
                model_fingerprint_hash=model_fingerprint_hash,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens,
                actual_cost_usd=actual_cost_usd,
                is_retry=is_retry,
                is_repair=is_repair,
                idempotency_key=idempotency_key,
                metadata=metadata or {},
            )
        )

    def record_explicit(
        self,
        *,
        execution_id: str,
        workspace_id: str,
        category: CostCategory,
        amount_usd: float | None,
        availability: CostAvailability,
        experiment_id: str | None = None,
        run_id: str | None = None,
        operation: str = "",
        description: str = "",
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CostEntry:
        """Record a fully-specified entry (e.g. infrastructure flat fee)."""
        return self.ledger.record(
            CostEntry(
                execution_id=execution_id,
                workspace_id=workspace_id,
                experiment_id=experiment_id,
                run_id=run_id,
                category=category,
                availability=availability,
                amount_usd=amount_usd,
                operation=operation,
                description=description,
                idempotency_key=idempotency_key,
                metadata=metadata or {},
            )
        )

    # -- reporting ----------------------------------------------------------

    def breakdown_for_execution(self, execution_id: str) -> CostBreakdown:
        return self.ledger.breakdown(execution_id=execution_id)

    def breakdown_for_experiment(self, experiment_id: str) -> CostBreakdown:
        return self.ledger.breakdown(experiment_id=experiment_id)

    def summary_for_execution(
        self,
        *,
        execution_id: str,
        succeeded: bool = True,
        budget_limit_usd: float | None = None,
    ) -> EconomicsSummary:
        bd = self.breakdown_for_execution(execution_id)
        attempts = 1
        successful = 1 if succeeded else 0
        cps = self.calculator.cost_per_successful_task(
            total_cost_usd=bd.total_known_usd,
            successful_tasks=successful,
        )
        cpa = self.calculator.cost_per_attempt(
            total_cost_usd=bd.total_known_usd,
            attempts=attempts,
        )
        remaining = None
        ratio = None
        if budget_limit_usd is not None and budget_limit_usd > 0:
            remaining = max(0.0, budget_limit_usd - bd.total_known_usd)
            ratio = bd.total_known_usd / budget_limit_usd
        return EconomicsSummary(
            subject_type="execution",
            subject_id=execution_id,
            breakdown=bd,
            cost_per_attempt_usd=cpa,
            cost_per_successful_task_usd=cps,
            successful_tasks=successful,
            attempts=attempts,
            budget_limit_usd=budget_limit_usd,
            budget_remaining_usd=remaining,
            budget_utilized_ratio=ratio,
        )

    def report_for_execution(
        self,
        *,
        execution_id: str,
        succeeded: bool = True,
        budget_limit_usd: float | None = None,
    ) -> EconomicsReport:
        summary = self.summary_for_execution(
            execution_id=execution_id,
            succeeded=succeeded,
            budget_limit_usd=budget_limit_usd,
        )
        entries = self.ledger.get_entries(execution_id=execution_id)
        return EconomicsReport(
            subject_type="execution",
            subject_id=execution_id,
            breakdown=summary.breakdown,
            summary=summary,
            entries=entries,
        )

    def compare_executions(
        self,
        *,
        baseline_execution_id: str,
        candidate_execution_id: str,
        baseline_label: str = "direct",
        candidate_label: str = "amplified",
        baseline_quality_score: float | None = None,
        candidate_quality_score: float | None = None,
        quality_threshold: float | None = None,
    ) -> CostComparisonResult:
        base = self.breakdown_for_execution(baseline_execution_id)
        cand = self.breakdown_for_execution(candidate_execution_id)
        return self.calculator.compare_paths(
            baseline_cost_usd=base.total_known_usd,
            candidate_cost_usd=cand.total_known_usd,
            baseline_label=baseline_label,
            candidate_label=candidate_label,
            baseline_quality_score=baseline_quality_score,
            candidate_quality_score=candidate_quality_score,
            quality_threshold=quality_threshold,
        )

    # -- internals ----------------------------------------------------------

    async def _estimate(
        self,
        request: RecordUsageRequest,
        snapshot_id: str | None,
    ) -> tuple[float | None, CostAvailability, dict[str, Any]]:
        meta: dict[str, Any] = {}
        if not snapshot_id:
            meta["estimate_error"] = "No pricing snapshot available"
            return None, CostAvailability.UNAVAILABLE, meta

        snapshot = await self.pricing.get(snapshot_id)
        if snapshot is None:
            meta["estimate_error"] = f"Pricing snapshot '{snapshot_id}' not found"
            return None, CostAvailability.UNAVAILABLE, meta

        if request.category in (
            CostCategory.MODEL_INFERENCE,
            CostCategory.HOSTED_INFERENCE,
            CostCategory.PLANNING,
            CostCategory.RETRIEVAL,
            CostCategory.VERIFICATION,
            CostCategory.RECOVERY,
        ) and request.provider and request.model_id:
            amount, err = self.pricing.estimate_model_cost(
                snapshot=snapshot,
                provider=request.provider,
                model_id=request.model_id,
                input_tokens=request.input_tokens,
                output_tokens=request.output_tokens,
                cached_tokens=request.cached_tokens,
            )
            if err:
                meta["estimate_error"] = err
                return None, CostAvailability.UNAVAILABLE, meta
            return amount, CostAvailability.ESTIMATED, meta

        if request.category == CostCategory.TOOLS and request.tool_name:
            amount, err = self.pricing.estimate_tool_cost(
                snapshot=snapshot,
                tool_name=request.tool_name,
                quantity=request.quantity,
            )
            if err:
                meta["estimate_error"] = err
                return None, CostAvailability.UNAVAILABLE, meta
            return amount, CostAvailability.ESTIMATED, meta

        if (
            request.category == CostCategory.ENVIRONMENT
            and request.duration_minutes is not None
        ):
            amount, err = self.pricing.estimate_environment_cost(
                snapshot=snapshot,
                duration_minutes=request.duration_minutes,
            )
            if err:
                meta["estimate_error"] = err
                return None, CostAvailability.UNAVAILABLE, meta
            return amount, CostAvailability.ESTIMATED, meta

        meta["estimate_error"] = (
            f"No estimator for category={request.category.value}"
        )
        return None, CostAvailability.UNAVAILABLE, meta

    async def _quick_estimate_model(
        self,
        *,
        provider: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int,
    ) -> float | None:
        if not self._default_snapshot_id:
            return None
        snap = await self.pricing.get(self._default_snapshot_id)
        if snap is None:
            return None
        amount, _ = self.pricing.estimate_model_cost(
            snapshot=snap,
            provider=provider,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
        )
        return amount