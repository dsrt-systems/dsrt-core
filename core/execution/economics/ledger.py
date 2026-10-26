"""
CostLedger — append-only attributable cost journal.

Rules:
- Every entry is attributable to an execution_id.
- Idempotency keys prevent double-charging on retries/worker restarts.
- UNAVAILABLE entries are retained (count + metadata) even with amount=None.
- Totals separate actual vs estimated vs unavailable.
"""

from __future__ import annotations

import logging
from typing import Iterable

from core.execution.economics.contracts import (
    CategoryAmount,
    CostAvailability,
    CostBreakdown,
    CostCategory,
    CostEntry,
)

logger = logging.getLogger(__name__)


class CostLedger:
    """In-memory ledger with the same semantics production DB-backed ledger uses."""

    def __init__(self) -> None:
        self._entries: list[CostEntry] = []
        self._by_idempotency: dict[str, str] = {}  # key -> entry_id

    # -- write --------------------------------------------------------------

    def record(self, entry: CostEntry) -> CostEntry:
        """
        Append a cost entry. If idempotency_key matches an existing entry,
        return the original (no double-charge).
        """
        if entry.idempotency_key:
            existing_id = self._by_idempotency.get(entry.idempotency_key)
            if existing_id:
                for e in self._entries:
                    if e.entry_id == existing_id:
                        logger.debug(
                            "Idempotent cost hit for key=%s entry=%s",
                            entry.idempotency_key,
                            existing_id,
                        )
                        return e

        if entry.availability != CostAvailability.UNAVAILABLE:
            if entry.amount_usd is None:
                raise ValueError(
                    f"amount_usd is required for availability={entry.availability}"
                )
            if entry.amount_usd < 0:
                raise ValueError("amount_usd cannot be negative")
        else:
            # Force amount to None for unavailable to avoid fake zeros
            entry = entry.model_copy(update={"amount_usd": None})

        self._entries.append(entry)
        if entry.idempotency_key:
            self._by_idempotency[entry.idempotency_key] = entry.entry_id
        return entry

    def record_many(self, entries: Iterable[CostEntry]) -> list[CostEntry]:
        return [self.record(e) for e in entries]

    # -- read ---------------------------------------------------------------

    def get_entries(
        self,
        *,
        execution_id: str | None = None,
        experiment_id: str | None = None,
        run_id: str | None = None,
        workspace_id: str | None = None,
        category: CostCategory | None = None,
    ) -> list[CostEntry]:
        result = list(self._entries)
        if execution_id is not None:
            result = [e for e in result if e.execution_id == execution_id]
        if experiment_id is not None:
            result = [e for e in result if e.experiment_id == experiment_id]
        if run_id is not None:
            result = [e for e in result if e.run_id == run_id]
        if workspace_id is not None:
            result = [e for e in result if e.workspace_id == workspace_id]
        if category is not None:
            result = [e for e in result if e.category == category]
        return result

    def spent_usd(
        self,
        *,
        execution_id: str | None = None,
        experiment_id: str | None = None,
        run_id: str | None = None,
        workspace_id: str | None = None,
        include_estimated: bool = True,
    ) -> float:
        entries = self.get_entries(
            execution_id=execution_id,
            experiment_id=experiment_id,
            run_id=run_id,
            workspace_id=workspace_id,
        )
        total = 0.0
        for e in entries:
            if e.availability == CostAvailability.UNAVAILABLE:
                continue
            if e.availability == CostAvailability.ESTIMATED and not include_estimated:
                continue
            total += e.billable_amount_usd
        return total

    def breakdown(
        self,
        *,
        execution_id: str | None = None,
        experiment_id: str | None = None,
        run_id: str | None = None,
        workspace_id: str | None = None,
    ) -> CostBreakdown:
        entries = self.get_entries(
            execution_id=execution_id,
            experiment_id=experiment_id,
            run_id=run_id,
            workspace_id=workspace_id,
        )
        bd = CostBreakdown(
            execution_id=execution_id,
            experiment_id=experiment_id,
            run_id=run_id,
        )
        by_cat: dict[str, CategoryAmount] = {}

        for e in entries:
            bd.entry_count += 1
            bd.total_input_tokens += e.input_tokens
            bd.total_output_tokens += e.output_tokens
            bd.total_cached_tokens += e.cached_tokens

            cat_key = e.category.value
            if cat_key not in by_cat:
                by_cat[cat_key] = CategoryAmount(category=e.category)
            ca = by_cat[cat_key]
            ca.entry_count += 1

            if e.availability == CostAvailability.ACTUAL:
                amt = e.billable_amount_usd
                ca.actual_usd += amt
                bd.total_actual_usd += amt
            elif e.availability == CostAvailability.ESTIMATED:
                amt = e.billable_amount_usd
                ca.estimated_usd += amt
                bd.total_estimated_usd += amt
            else:
                ca.unavailable_count += 1
                bd.unavailable_entry_count += 1
                bd.has_unavailable_costs = True

        bd.total_known_usd = bd.total_actual_usd + bd.total_estimated_usd
        bd.by_category = by_cat

        if bd.has_unavailable_costs:
            bd.notes.append(
                f"{bd.unavailable_entry_count} cost entries are UNAVAILABLE "
                f"and excluded from known totals."
            )
        return bd

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        """Test helper only."""
        self._entries.clear()
        self._by_idempotency.clear()