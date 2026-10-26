"""
C10.8 — Economics & Cost Ledger.

Authoritative cost accounting for Direct, Amplified, and Experiment runs.
Separates actual / estimated / unavailable costs. Enforces budgets.
Computes cost-per-successful-task and fair savings only when justified.
"""

from core.execution.economics.contracts import (
    CostAvailability,
    CostCategory,
    CostEntry,
    CostBreakdown,
    BudgetDefinition,
    BudgetCheckResult,
    BudgetDecision,
    EconomicsSummary,
)
from core.execution.economics.pricing import (
    PricingSnapshot,
    PricingDirectory,
    ModelPrice,
    InMemoryPricingStore,
)
from core.execution.economics.ledger import CostLedger
from core.execution.economics.budget import BudgetEnforcer, BudgetExceededError
from core.execution.economics.calculations import CostCalculator, CostComparisonResult
from core.execution.economics.service import (
    EconomicsEngine,
    RecordUsageRequest,
    EconomicsReport,
)

__all__ = [
    # contracts
    "CostAvailability",
    "CostCategory",
    "CostEntry",
    "CostBreakdown",
    "BudgetDefinition",
    "BudgetCheckResult",
    "BudgetDecision",
    "EconomicsSummary",
    # pricing
    "PricingSnapshot",
    "PricingDirectory",
    "ModelPrice",
    "InMemoryPricingStore",
    # ledger
    "CostLedger",
    # budget
    "BudgetEnforcer",
    "BudgetExceededError",
    # calculations
    "CostCalculator",
    "CostComparisonResult",
    # service
    "EconomicsEngine",
    "RecordUsageRequest",
    "EconomicsReport",
]