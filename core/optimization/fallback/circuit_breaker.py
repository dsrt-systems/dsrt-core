"""
Circuit Breaker and Fallback Controller for C11 Optimization System.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from core.storage.models.optimization_c11_governance import FallbackStateModel
from schemas.domain.governance import FallbackMode

logger = logging.getLogger(__name__)

SINGLETON_STATE_ID = "c11-global-fallback-state"


class _FallbackStateView:
    """Lightweight view returned by get_state()."""
    def __init__(self, mode: FallbackMode, failure_count: int,
                 last_failure_at=None, last_success_at=None,
                 total_fallbacks: int = 0, active_reason: str = None):
        self.mode = mode
        self.failure_count = failure_count
        self.last_failure_at = last_failure_at
        self.last_success_at = last_success_at
        self.total_fallbacks = total_fallbacks
        self.active_reason = active_reason


class FallbackCircuitBreaker:
    FAILURE_THRESHOLD = 5
    FAILURE_WINDOW_SEC = 60
    RECOVERY_WAIT_SEC = 300

    def __init__(self, db: Session = None, db_session: Session = None):
        self.db = db or db_session

    def _get_or_create_model(self) -> FallbackStateModel:
        model = self.db.query(FallbackStateModel).filter(
            FallbackStateModel.state_id == SINGLETON_STATE_ID
        ).first()
        if not model:
            model = FallbackStateModel(
                state_id=SINGLETON_STATE_ID,
                mode=FallbackMode.HEALTHY.value,
                failure_count=0,
            )
            self.db.add(model)
            self.db.commit()
            self.db.refresh(model)
        return model

    def get_state(self) -> _FallbackStateView:
        model = self._get_or_create_model()
        return _FallbackStateView(
            mode=FallbackMode(model.mode),
            failure_count=model.failure_count,
            last_failure_at=model.last_failure_at,
            last_success_at=model.last_success_at,
            active_reason=model.reason,
        )

    def is_healthy(self) -> bool:
        return self.get_state().mode == FallbackMode.HEALTHY

    def should_use_fallback(self) -> bool:
        return self.get_state().mode in (FallbackMode.DEGRADED, FallbackMode.CRITICAL)

    def record_failure(self, reason: str) -> _FallbackStateView:
        model = self._get_or_create_model()
        now = datetime.now(timezone.utc)
        model.failure_count += 1
        model.last_failure_at = now
        model.reason = reason
        if model.failure_count >= self.FAILURE_THRESHOLD:
            model.mode = FallbackMode.DEGRADED.value
            model.circuit_opened_at = now
        self.db.commit()
        self.db.refresh(model)
        return self.get_state()

    def record_success(self) -> _FallbackStateView:
        model = self._get_or_create_model()
        now = datetime.now(timezone.utc)
        model.last_success_at = now
        if model.mode != FallbackMode.HEALTHY.value:
            if model.last_failure_at:
                elapsed = (now - model.last_failure_at).total_seconds()
                if elapsed >= self.RECOVERY_WAIT_SEC:
                    model.mode = FallbackMode.HEALTHY.value
                    model.failure_count = 0
                    model.reason = None
        self.db.commit()
        self.db.refresh(model)
        return self.get_state()

    def reset(self) -> _FallbackStateView:
        model = self._get_or_create_model()
        model.mode = FallbackMode.HEALTHY.value
        model.failure_count = 0
        model.reason = None
        model.circuit_opened_at = None
        self.db.commit()
        self.db.refresh(model)
        return self.get_state()

    def force_mode(self, mode: FallbackMode, reason: str) -> _FallbackStateView:
        model = self._get_or_create_model()
        model.mode = mode.value
        model.reason = reason
        self.db.commit()
        self.db.refresh(model)
        return self.get_state()

    def get_fallback_plan(self, request_task_id: str = "", request_id: str = "",
                          tenant_id: str = "", reason: str = "circuit_open") -> Dict[str, Any]:
        model = self._get_or_create_model()
        model.failure_count = model.failure_count  # no-op touch
        self.db.commit()

        return {
            "selected_model": "claude-3-5-sonnet",
            "selected_strategies": ["minimal_prompting"],
            "verification_plan": {
                "security_checks_included": True,
                "mandatory_security_enforced": True,
                "required_checks": ["security_scan", "syntax_check"],
            },
            "estimated_cost": 0.06,
            "estimated_latency_ms": 6200.0,
            "estimated_quality": 0.85,
            "fallback_reason": f"SAFE FALLBACK MODE ({reason})",
            "warning": "System is in degraded mode. Using safe fallback plan.",
        }
