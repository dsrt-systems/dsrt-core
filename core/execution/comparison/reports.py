# Path: core/execution/comparison/reports.py
"""
Human- and API-facing comparison report builder.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List

from core.execution.comparison.contracts import ComparisonResult


class ComparisonReportBuilder:
    """Builds structured comparison reports for APIs and UIs."""

    def build(self, result: ComparisonResult) -> Dict[str, Any]:
        return {
            "comparison_id": result.comparison_id,
            "experiment_id": result.experiment_id,
            "workspace_id": result.workspace_id,
            "outcome": {
                "kind": result.outcome_kind.value,
                "summary": result.outcome_summary,
            },
            "configurations": [
                {
                    "id": cid,
                    "label": result.configuration_labels.get(cid, cid),
                }
                for cid in result.configurations
            ],
            "recommendations": {
                "successful_configuration_ids": result.successful_configuration_ids,
                "highest_quality_configuration_id": result.highest_quality_configuration_id,
                "cost_efficient_configuration_id": result.cost_efficient_configuration_id,
                "lowest_latency_configuration_id": result.lowest_latency_configuration_id,
                # Explicit: no universal winner field
                "universal_winner": None,
            },
            "dimensions": {
                "quality": result.quality_comparison.model_dump(mode="json"),
                "completion": result.completion_comparison.model_dump(mode="json"),
                "correctness": result.correctness_comparison.model_dump(mode="json"),
                "reliability": result.reliability_comparison.model_dump(mode="json"),
                "cost": result.cost_comparison.model_dump(mode="json"),
                "latency": result.latency_comparison.model_dump(mode="json"),
                "verification": result.verification_comparison.model_dump(mode="json"),
                "recovery": result.recovery_comparison.model_dump(mode="json"),
            },
            "economics": {
                "baseline_configuration_id": result.baseline_configuration_id,
                "cost_savings_vs_baseline": result.cost_savings_vs_baseline,
                "cost_savings_claimable": result.cost_savings_claimable,
            },
            "findings": list(result.findings),
            "limitations": list(result.limitations),
            "protocol_valid": result.protocol_valid,
            "evaluator_version": result.evaluator_version,
            "created_at": result.created_at.isoformat()
            if isinstance(result.created_at, datetime.datetime)
            else result.created_at,
        }

    def build_markdown(self, result: ComparisonResult) -> str:
        lines: List[str] = []
        lines.append(f"# Comparison Report — `{result.experiment_id}`")
        lines.append("")
        lines.append(f"**Outcome:** {result.outcome_kind.value}")
        lines.append("")
        lines.append(result.outcome_summary)
        lines.append("")
        lines.append("## Configurations")
        for cid in result.configurations:
            label = result.configuration_labels.get(cid, cid)
            marker = ""
            if cid in result.successful_configuration_ids:
                marker += " ✓ success"
            if cid == result.cost_efficient_configuration_id:
                marker += " 💰 cost-efficient"
            if cid == result.highest_quality_configuration_id:
                marker += " ★ quality"
            lines.append(f"- `{cid}` — {label}{marker}")
        lines.append("")
        lines.append("## Economics")
        lines.append(
            f"- Savings vs baseline: {result.cost_savings_vs_baseline} "
            f"(claimable={result.cost_savings_claimable})"
        )
        lines.append("")
        if result.findings:
            lines.append("## Findings")
            for f in result.findings:
                lines.append(f"- {f}")
            lines.append("")
        if result.limitations:
            lines.append("## Limitations")
            for lim in result.limitations:
                lines.append(f"- {lim}")
            lines.append("")
        lines.append("_No universal winner is forced. Rankings are dimension-specific._")
        return "\n".join(lines)