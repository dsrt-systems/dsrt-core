"""
C10.8 — Economics & Cost Ledger tests.

Covers:
1. Pricing snapshots & model/tool/env estimates
2. CostLedger — record, idempotency, breakdown, actual/estimated/unavailable
3. BudgetEnforcer — allow/warn/deny, per-call caps, multi-scope
4. CostCalculator — per-task, savings quality gate
5. EconomicsEngine — end-to-end recording, auth, reports, comparison
"""

from __future__ import annotations

import pytest

from core.execution.economics.contracts import (
    BudgetDecision,
    BudgetDefinition,
    BudgetScope,
    CostAvailability,
    CostCategory,
    CostEntry,
)
from core.execution.economics.pricing import (
    ModelPrice,
    PricingDirectory,
    PricingSnapshot,
    ToolPrice,
)
from core.execution.economics.ledger import CostLedger
from core.execution.economics.budget import BudgetEnforcer, BudgetExceededError
from core.execution.economics.calculations import CostCalculator
from core.execution.economics.service import (
    EconomicsEngine,
    RecordUsageRequest,
)


# =====================================================================
# Helpers
# =====================================================================

def _snapshot() -> PricingSnapshot:
    return PricingSnapshot(
        name="test",
        source="manual",
        model_prices=[
            ModelPrice(
                provider="openai",
                model_id="gpt-4o",
                input_price_per_1k_usd=0.005,
                output_price_per_1k_usd=0.015,
                cached_input_price_per_1k_usd=0.0025,
            ),
            ModelPrice(
                provider="openai",
                model_id="gpt-4o-mini",
                input_price_per_1k_usd=0.00015,
                output_price_per_1k_usd=0.0006,
            ),
        ],
        tool_prices=[
            ToolPrice(tool_name="shell", price_per_unit_usd=0.001),
            ToolPrice(tool_name="browser", price_per_unit_usd=0.01),
        ],
        environment_price_per_minute_usd=0.002,
    )


async def _engine_with_pricing() -> EconomicsEngine:
    engine = EconomicsEngine()
    await engine.set_pricing_snapshot(_snapshot())
    return engine


# =====================================================================
# 1. Pricing
# =====================================================================

class TestPricing:
    def test_estimate_model_cost(self):
        d = PricingDirectory()
        snap = _snapshot()
        amount, err = d.estimate_model_cost(
            snapshot=snap,
            provider="openai",
            model_id="gpt-4o",
            input_tokens=1000,
            output_tokens=500,
        )
        assert err is None
        # 1*0.005 + 0.5*0.015 = 0.005 + 0.0075 = 0.0125
        assert amount == pytest.approx(0.0125)

    def test_estimate_model_cost_with_cache(self):
        d = PricingDirectory()
        amount, err = d.estimate_model_cost(
            snapshot=_snapshot(),
            provider="openai",
            model_id="gpt-4o",
            input_tokens=1000,
            output_tokens=0,
            cached_tokens=400,
        )
        assert err is None
        # billable input 600 @ 0.005/1k + cached 400 @ 0.0025/1k
        assert amount == pytest.approx(0.6 * 0.005 + 0.4 * 0.0025)

    def test_unknown_model_returns_none(self):
        d = PricingDirectory()
        amount, err = d.estimate_model_cost(
            snapshot=_snapshot(),
            provider="openai",
            model_id="nope",
            input_tokens=10,
            output_tokens=10,
        )
        assert amount is None
        assert err is not None

    def test_tool_and_env_estimates(self):
        d = PricingDirectory()
        snap = _snapshot()
        t, _ = d.estimate_tool_cost(snapshot=snap, tool_name="browser", quantity=3)
        assert t == pytest.approx(0.03)
        e, _ = d.estimate_environment_cost(snapshot=snap, duration_minutes=10)
        assert e == pytest.approx(0.02)

    @pytest.mark.asyncio
    async def test_snapshot_roundtrip(self):
        d = PricingDirectory()
        snap = _snapshot()
        saved = await d.register(snap)
        got = await d.get(saved.snapshot_id)
        assert got is not None
        assert got.snapshot_id == saved.snapshot_id
        latest = await d.latest("test")
        assert latest is not None
        assert latest.snapshot_id == saved.snapshot_id


# =====================================================================
# 2. Ledger
# =====================================================================

class TestCostLedger:
    def test_record_actual_and_breakdown(self):
        ledger = CostLedger()
        ledger.record(
            CostEntry(
                execution_id="e1",
                workspace_id="ws",
                category=CostCategory.MODEL_INFERENCE,
                availability=CostAvailability.ACTUAL,
                amount_usd=0.05,
                input_tokens=100,
                output_tokens=50,
            )
        )
        ledger.record(
            CostEntry(
                execution_id="e1",
                workspace_id="ws",
                category=CostCategory.TOOLS,
                availability=CostAvailability.ESTIMATED,
                amount_usd=0.02,
            )
        )
        bd = ledger.breakdown(execution_id="e1")
        assert bd.total_actual_usd == pytest.approx(0.05)
        assert bd.total_estimated_usd == pytest.approx(0.02)
        assert bd.total_known_usd == pytest.approx(0.07)
        assert bd.total_input_tokens == 100
        assert "MODEL_INFERENCE" in bd.by_category
        assert "TOOLS" in bd.by_category

    def test_unavailable_excluded_from_totals_but_counted(self):
        ledger = CostLedger()
        ledger.record(
            CostEntry(
                execution_id="e1",
                workspace_id="ws",
                category=CostCategory.MODEL_INFERENCE,
                availability=CostAvailability.UNAVAILABLE,
                amount_usd=None,
            )
        )
        bd = ledger.breakdown(execution_id="e1")
        assert bd.total_known_usd == 0.0
        assert bd.unavailable_entry_count == 1
        assert bd.has_unavailable_costs is True
        assert len(bd.notes) >= 1

    def test_idempotency_prevents_double_charge(self):
        ledger = CostLedger()
        e1 = ledger.record(
            CostEntry(
                execution_id="e1",
                workspace_id="ws",
                category=CostCategory.MODEL_INFERENCE,
                availability=CostAvailability.ACTUAL,
                amount_usd=0.10,
                idempotency_key="call-1",
            )
        )
        e2 = ledger.record(
            CostEntry(
                execution_id="e1",
                workspace_id="ws",
                category=CostCategory.MODEL_INFERENCE,
                availability=CostAvailability.ACTUAL,
                amount_usd=0.10,
                idempotency_key="call-1",
            )
        )
        assert e1.entry_id == e2.entry_id
        assert ledger.entry_count == 1
        assert ledger.spent_usd(execution_id="e1") == pytest.approx(0.10)

    def test_rejects_negative_amount(self):
        ledger = CostLedger()
        with pytest.raises(ValueError, match="negative"):
            ledger.record(
                CostEntry(
                    execution_id="e1",
                    workspace_id="ws",
                    category=CostCategory.TOOLS,
                    availability=CostAvailability.ACTUAL,
                    amount_usd=-1.0,
                )
            )

    def test_requires_amount_for_actual(self):
        ledger = CostLedger()
        with pytest.raises(ValueError, match="amount_usd is required"):
            ledger.record(
                CostEntry(
                    execution_id="e1",
                    workspace_id="ws",
                    category=CostCategory.TOOLS,
                    availability=CostAvailability.ACTUAL,
                    amount_usd=None,
                )
            )

    def test_spent_can_exclude_estimated(self):
        ledger = CostLedger()
        ledger.record(
            CostEntry(
                execution_id="e1", workspace_id="ws",
                category=CostCategory.MODEL_INFERENCE,
                availability=CostAvailability.ACTUAL, amount_usd=0.05,
            )
        )
        ledger.record(
            CostEntry(
                execution_id="e1", workspace_id="ws",
                category=CostCategory.TOOLS,
                availability=CostAvailability.ESTIMATED, amount_usd=0.05,
            )
        )
        assert ledger.spent_usd(execution_id="e1", include_estimated=True) == pytest.approx(0.10)
        assert ledger.spent_usd(execution_id="e1", include_estimated=False) == pytest.approx(0.05)


# =====================================================================
# 3. Budget
# =====================================================================

class TestBudgetEnforcer:
    def _enforcer_with_spend(self, spent: float = 0.0) -> tuple[BudgetEnforcer, CostLedger, BudgetDefinition]:
        ledger = CostLedger()
        if spent > 0:
            ledger.record(
                CostEntry(
                    execution_id="e1",
                    workspace_id="ws",
                    category=CostCategory.MODEL_INFERENCE,
                    availability=CostAvailability.ACTUAL,
                    amount_usd=spent,
                )
            )
        enf = BudgetEnforcer(ledger)
        budget = enf.register(
            BudgetDefinition(
                scope=BudgetScope.EXECUTION,
                scope_id="e1",
                limit_usd=1.0,
                warn_threshold_ratio=0.8,
                hard_limit=True,
            )
        )
        return enf, ledger, budget

    def test_allow(self):
        enf, _, budget = self._enforcer_with_spend(0.1)
        result = enf.check(budget=budget, pending_usd=0.2)
        assert result.decision == BudgetDecision.ALLOW
        assert result.projected_usd == pytest.approx(0.3)

    def test_warn_at_threshold(self):
        enf, _, budget = self._enforcer_with_spend(0.7)
        result = enf.check(budget=budget, pending_usd=0.15)  # 0.85 >= 0.8
        assert result.decision == BudgetDecision.WARN

    def test_deny_over_limit(self):
        enf, _, budget = self._enforcer_with_spend(0.9)
        result = enf.check(budget=budget, pending_usd=0.2)  # 1.1 > 1.0
        assert result.decision == BudgetDecision.DENY

    def test_authorize_or_raise(self):
        enf, _, budget = self._enforcer_with_spend(0.95)
        with pytest.raises(BudgetExceededError):
            enf.authorize_or_raise(budget=budget, pending_usd=0.10)

    def test_soft_limit_warns_instead_of_deny(self):
        ledger = CostLedger()
        enf = BudgetEnforcer(ledger)
        budget = enf.register(
            BudgetDefinition(
                scope=BudgetScope.EXECUTION,
                scope_id="e1",
                limit_usd=1.0,
                hard_limit=False,
            )
        )
        result = enf.check(budget=budget, pending_usd=1.5)
        assert result.decision == BudgetDecision.WARN

    def test_per_call_model_cap(self):
        ledger = CostLedger()
        enf = BudgetEnforcer(ledger)
        budget = enf.register(
            BudgetDefinition(
                scope=BudgetScope.EXECUTION,
                scope_id="e1",
                limit_usd=10.0,
                max_single_model_call_usd=0.05,
            )
        )
        result = enf.check(
            budget=budget,
            pending_usd=0.20,
            category=CostCategory.MODEL_INFERENCE,
        )
        assert result.decision == BudgetDecision.DENY
        assert "per-call cap" in result.reason

    def test_repair_cap(self):
        ledger = CostLedger()
        enf = BudgetEnforcer(ledger)
        budget = enf.register(
            BudgetDefinition(
                scope=BudgetScope.EXECUTION,
                scope_id="e1",
                limit_usd=10.0,
                max_repair_usd=0.02,
            )
        )
        result = enf.check(
            budget=budget,
            pending_usd=0.05,
            category=CostCategory.RECOVERY,
        )
        assert result.decision == BudgetDecision.DENY

    def test_multi_scope_deny(self):
        ledger = CostLedger()
        ledger.record(
            CostEntry(
                execution_id="e1", workspace_id="ws", experiment_id="exp1",
                category=CostCategory.MODEL_INFERENCE,
                availability=CostAvailability.ACTUAL, amount_usd=0.8,
            )
        )
        enf = BudgetEnforcer(ledger)
        b_exec = enf.register(
            BudgetDefinition(
                scope=BudgetScope.EXECUTION, scope_id="e1", limit_usd=5.0,
            )
        )
        b_exp = enf.register(
            BudgetDefinition(
                scope=BudgetScope.EXPERIMENT, scope_id="exp1", limit_usd=1.0,
            )
        )
        with pytest.raises(BudgetExceededError):
            enf.authorize_all(
                budgets=[b_exec, b_exp],
                pending_usd=0.3,  # exp would be 1.1
            )


# =====================================================================
# 4. Calculator
# =====================================================================

class TestCostCalculator:
    def test_cost_per_successful_task(self):
        calc = CostCalculator(CostLedger())
        assert calc.cost_per_successful_task(
            total_cost_usd=1.0, successful_tasks=4,
        ) == pytest.approx(0.25)
        assert calc.cost_per_successful_task(
            total_cost_usd=1.0, successful_tasks=0,
        ) is None

    def test_cost_per_attempt(self):
        calc = CostCalculator(CostLedger())
        assert calc.cost_per_attempt(total_cost_usd=0.9, attempts=3) == pytest.approx(0.3)
        assert calc.cost_per_attempt(total_cost_usd=0.9, attempts=0) is None

    def test_savings_valid_when_quality_comparable(self):
        calc = CostCalculator(CostLedger())
        result = calc.compare_paths(
            baseline_cost_usd=1.0,
            candidate_cost_usd=0.6,
            baseline_quality_score=0.8,
            candidate_quality_score=0.85,
        )
        assert result.valid is True
        assert result.savings_ratio == pytest.approx(0.4)
        assert result.savings_percent == pytest.approx(40.0)
        assert result.quality_comparable is True

    def test_savings_invalid_without_quality(self):
        calc = CostCalculator(CostLedger())
        result = calc.compare_paths(
            baseline_cost_usd=1.0,
            candidate_cost_usd=0.5,
        )
        assert result.valid is False
        assert result.savings_ratio == pytest.approx(0.5)  # computed but not claimable
        assert any("Quality scores missing" in x for x in result.limitations)

    def test_savings_invalid_when_quality_drops(self):
        calc = CostCalculator(CostLedger())
        result = calc.compare_paths(
            baseline_cost_usd=1.0,
            candidate_cost_usd=0.4,
            baseline_quality_score=0.9,
            candidate_quality_score=0.5,
        )
        assert result.valid is False
        assert result.quality_comparable is False

    def test_zero_baseline_undefined(self):
        calc = CostCalculator(CostLedger())
        result = calc.compare_paths(
            baseline_cost_usd=0.0,
            candidate_cost_usd=0.5,
            baseline_quality_score=1.0,
            candidate_quality_score=1.0,
        )
        assert result.valid is False
        assert result.savings_ratio is None

    def test_category_share(self):
        ledger = CostLedger()
        ledger.record(
            CostEntry(
                execution_id="e1", workspace_id="ws",
                category=CostCategory.MODEL_INFERENCE,
                availability=CostAvailability.ACTUAL, amount_usd=0.8,
            )
        )
        ledger.record(
            CostEntry(
                execution_id="e1", workspace_id="ws",
                category=CostCategory.TOOLS,
                availability=CostAvailability.ACTUAL, amount_usd=0.2,
            )
        )
        calc = CostCalculator(ledger)
        bd = calc.execution_total("e1")
        share = calc.category_share(bd)
        assert share["MODEL_INFERENCE"] == pytest.approx(0.8)
        assert share["TOOLS"] == pytest.approx(0.2)


# =====================================================================
# 5. EconomicsEngine
# =====================================================================

class TestEconomicsEngine:
    @pytest.mark.asyncio
    async def test_record_actual_model_cost(self):
        engine = await _engine_with_pricing()
        entry = await engine.record_model_call(
            execution_id="e1",
            workspace_id="ws",
            provider="openai",
            model_id="gpt-4o",
            input_tokens=1000,
            output_tokens=500,
            actual_cost_usd=0.02,
            authorize=False,
        )
        assert entry.availability == CostAvailability.ACTUAL
        assert entry.amount_usd == pytest.approx(0.02)
        bd = engine.breakdown_for_execution("e1")
        assert bd.total_actual_usd == pytest.approx(0.02)

    @pytest.mark.asyncio
    async def test_record_estimated_when_no_actual(self):
        engine = await _engine_with_pricing()
        entry = await engine.record_model_call(
            execution_id="e1",
            workspace_id="ws",
            provider="openai",
            model_id="gpt-4o",
            input_tokens=1000,
            output_tokens=500,
            authorize=False,
        )
        assert entry.availability == CostAvailability.ESTIMATED
        assert entry.amount_usd == pytest.approx(0.0125)

    @pytest.mark.asyncio
    async def test_record_unavailable_without_price(self):
        engine = EconomicsEngine()  # no snapshot
        entry = await engine.record_usage(
            RecordUsageRequest(
                execution_id="e1",
                workspace_id="ws",
                category=CostCategory.MODEL_INFERENCE,
                provider="openai",
                model_id="gpt-4o",
                input_tokens=100,
                output_tokens=50,
            )
        )
        assert entry.availability == CostAvailability.UNAVAILABLE
        assert entry.amount_usd is None
        bd = engine.breakdown_for_execution("e1")
        assert bd.has_unavailable_costs is True
        assert bd.total_known_usd == 0.0

    @pytest.mark.asyncio
    async def test_tool_usage_estimated(self):
        engine = await _engine_with_pricing()
        entry = await engine.record_usage(
            RecordUsageRequest(
                execution_id="e1",
                workspace_id="ws",
                category=CostCategory.TOOLS,
                tool_name="browser",
                quantity=2,
                operation="tool.browser",
            )
        )
        assert entry.availability == CostAvailability.ESTIMATED
        assert entry.amount_usd == pytest.approx(0.02)

    @pytest.mark.asyncio
    async def test_budget_blocks_model_call(self):
        engine = await _engine_with_pricing()
        engine.register_execution_budget(execution_id="e1", limit_usd=0.01)
        with pytest.raises(BudgetExceededError):
            await engine.record_model_call(
                execution_id="e1",
                workspace_id="ws",
                provider="openai",
                model_id="gpt-4o",
                input_tokens=1000,
                output_tokens=500,
                # estimated ~0.0125 > 0.01
                authorize=True,
            )

    @pytest.mark.asyncio
    async def test_idempotent_model_call(self):
        engine = await _engine_with_pricing()
        kwargs = dict(
            execution_id="e1",
            workspace_id="ws",
            provider="openai",
            model_id="gpt-4o",
            input_tokens=100,
            output_tokens=50,
            actual_cost_usd=0.01,
            idempotency_key="req-99",
            authorize=False,
        )
        a = await engine.record_model_call(**kwargs)
        b = await engine.record_model_call(**kwargs)
        assert a.entry_id == b.entry_id
        assert engine.ledger.entry_count == 1

    @pytest.mark.asyncio
    async def test_summary_and_report(self):
        engine = await _engine_with_pricing()
        await engine.record_model_call(
            execution_id="e1", workspace_id="ws",
            provider="openai", model_id="gpt-4o",
            input_tokens=1000, output_tokens=0,
            actual_cost_usd=0.05, authorize=False,
        )
        summary = engine.summary_for_execution(
            execution_id="e1", succeeded=True, budget_limit_usd=1.0,
        )
        assert summary.cost_per_successful_task_usd == pytest.approx(0.05)
        assert summary.cost_per_attempt_usd == pytest.approx(0.05)
        assert summary.budget_remaining_usd == pytest.approx(0.95)
        assert summary.budget_utilized_ratio == pytest.approx(0.05)

        report = engine.report_for_execution(execution_id="e1", succeeded=True)
        assert len(report.entries) == 1
        assert report.breakdown.total_known_usd == pytest.approx(0.05)

    @pytest.mark.asyncio
    async def test_summary_failed_task_no_cost_per_success(self):
        engine = await _engine_with_pricing()
        await engine.record_model_call(
            execution_id="e1", workspace_id="ws",
            provider="openai", model_id="gpt-4o",
            input_tokens=10, output_tokens=10,
            actual_cost_usd=0.01, authorize=False,
        )
        summary = engine.summary_for_execution(execution_id="e1", succeeded=False)
        assert summary.cost_per_successful_task_usd is None
        assert summary.successful_tasks == 0

    @pytest.mark.asyncio
    async def test_compare_executions_with_quality(self):
        engine = await _engine_with_pricing()
        await engine.record_model_call(
            execution_id="direct-1", workspace_id="ws",
            provider="openai", model_id="gpt-4o",
            input_tokens=1000, output_tokens=500,
            actual_cost_usd=1.0, authorize=False,
        )
        await engine.record_model_call(
            execution_id="amp-1", workspace_id="ws",
            provider="openai", model_id="gpt-4o",
            input_tokens=2000, output_tokens=800,
            actual_cost_usd=0.7, authorize=False,
        )
        cmp = engine.compare_executions(
            baseline_execution_id="direct-1",
            candidate_execution_id="amp-1",
            baseline_quality_score=0.8,
            candidate_quality_score=0.9,
        )
        assert cmp.valid is True
        assert cmp.savings_ratio == pytest.approx(0.3)

    @pytest.mark.asyncio
    async def test_compare_without_quality_not_valid(self):
        engine = await _engine_with_pricing()
        await engine.record_model_call(
            execution_id="d", workspace_id="ws",
            provider="openai", model_id="gpt-4o",
            input_tokens=10, output_tokens=10,
            actual_cost_usd=1.0, authorize=False,
        )
        await engine.record_model_call(
            execution_id="a", workspace_id="ws",
            provider="openai", model_id="gpt-4o",
            input_tokens=10, output_tokens=10,
            actual_cost_usd=0.5, authorize=False,
        )
        cmp = engine.compare_executions(
            baseline_execution_id="d",
            candidate_execution_id="a",
        )
        assert cmp.valid is False

    @pytest.mark.asyncio
    async def test_explicit_infrastructure_cost(self):
        engine = EconomicsEngine()
        entry = engine.record_explicit(
            execution_id="e1",
            workspace_id="ws",
            category=CostCategory.INFRASTRUCTURE,
            amount_usd=0.001,
            availability=CostAvailability.ACTUAL,
            operation="platform.overhead",
        )
        assert entry.category == CostCategory.INFRASTRUCTURE
        assert engine.breakdown_for_execution("e1").total_known_usd == pytest.approx(0.001)

    @pytest.mark.asyncio
    async def test_experiment_budget_across_runs(self):
        engine = await _engine_with_pricing()
        engine.register_experiment_budget(experiment_id="exp1", limit_usd=0.02)

        await engine.record_model_call(
            execution_id="e1", workspace_id="ws", experiment_id="exp1",
            provider="openai", model_id="gpt-4o",
            input_tokens=100, output_tokens=100,
            actual_cost_usd=0.015, authorize=True,
        )
        with pytest.raises(BudgetExceededError):
            await engine.record_model_call(
                execution_id="e2", workspace_id="ws", experiment_id="exp1",
                provider="openai", model_id="gpt-4o",
                input_tokens=100, output_tokens=100,
                actual_cost_usd=0.015, authorize=True,
            )