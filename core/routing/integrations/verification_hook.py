"""C9.10 - Verification Routing Hook.

Maps C9 route decisions to C7 verification configurations
using QualityLevel from task requirements.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.routing.contracts import RouteDecision
from core.routing.enums import QualityLevel


@dataclass(frozen=True)
class VerificationConfig:
    quality_level: QualityLevel
    checks_enabled: tuple[str, ...]
    strictness: float
    max_verification_latency_ms: int
    require_human_review: bool
    metadata: dict[str, Any] = field(default_factory=dict)


class VerificationRoutingHook:
    CHECK_SETS: dict[QualityLevel, tuple[str, ...]] = {
        QualityLevel.MINIMUM: ("schema_check", "completeness_check"),
        QualityLevel.STANDARD: (
            "schema_check", "completeness_check",
            "constraint_check", "claim_check",
        ),
        QualityLevel.HIGH: (
            "schema_check", "completeness_check",
            "constraint_check", "claim_check",
            "citation_check", "artifact_check",
        ),
        QualityLevel.STRICT: (
            "schema_check", "completeness_check",
            "constraint_check", "claim_check",
            "citation_check", "artifact_check",
            "tool_check", "state_check",
        ),
    }
    STRICTNESS: dict[QualityLevel, float] = {
        QualityLevel.MINIMUM: 0.25,
        QualityLevel.STANDARD: 0.5,
        QualityLevel.HIGH: 0.75,
        QualityLevel.STRICT: 1.0,
    }
    LATENCY: dict[QualityLevel, int] = {
        QualityLevel.MINIMUM: 500,
        QualityLevel.STANDARD: 2000,
        QualityLevel.HIGH: 5000,
        QualityLevel.STRICT: 15000,
    }

    def get_verification_config(self, decision: RouteDecision) -> VerificationConfig:
        level = self._determine_level(decision)
        return VerificationConfig(
            quality_level=level,
            checks_enabled=self.CHECK_SETS.get(level, self.CHECK_SETS[QualityLevel.STANDARD]),
            strictness=self.STRICTNESS.get(level, 0.5),
            max_verification_latency_ms=self.LATENCY.get(level, 2000),
            require_human_review=level in (QualityLevel.HIGH, QualityLevel.STRICT),
            metadata={
                "decision_id": decision.decision_id,
                "task_id": decision.task_id,
                "source": "c9_routing",
            },
        )

    def _determine_level(self, decision: RouteDecision) -> QualityLevel:
        base = QualityLevel.STANDARD
        reqs = decision.requirements
        if reqs is not None:
            base = reqs.quality.overall
            if reqs.security.external_write_actions:
                base = self._max(base, QualityLevel.HIGH)
            if reqs.security.requires_sandbox:
                base = self._max(base, QualityLevel.HIGH)
            if reqs.security.max_privilege_level in ("elevated", "admin"):
                base = self._max(base, QualityLevel.STRICT)
        reason = decision.decision_reason or {}
        if str(reason.get("confidence", "")).upper() == "LOW":
            base = self._max(base, QualityLevel.HIGH)
        return base

    @staticmethod
    def _max(a: QualityLevel, b: QualityLevel) -> QualityLevel:
        order = [QualityLevel.MINIMUM, QualityLevel.STANDARD, QualityLevel.HIGH, QualityLevel.STRICT]
        return order[max(order.index(a) if a in order else 1, order.index(b) if b in order else 1)]
