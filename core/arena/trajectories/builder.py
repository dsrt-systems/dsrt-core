"""
Trajectory Builder (C8 §16-19, §43).

Converts raw C1 ExecutionEvent records into structured Arena trajectories.

Key principles:
  - Trajectory is more important than final answer (C8 §18)
  - Events are normalized, not duplicated (C8 §19)
  - Sensitive content is referenced, not embedded (C8 §19)
  - Configuration fingerprint ensures reproducibility (C8 §43)

Architecture:
    C1 ExecutionEvents (append-only, monotonic sequence)
        ↓
    TrajectoryBuilder.build_trajectory()
        ↓
    Normalized TrajectoryEvent records
        ↓
    Trajectory summary (counts, hashes, duration)
        ↓
    Persisted TrajectoryORM + TrajectoryEventORM
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from schemas.domain.arena import TrajectoryEvent
from schemas.domain.enums import EventType

from core.kernel.fingerprint import content_hash
from core.observability.logging import get_logger
from core.repositories.event_repository import EventRepository
from core.storage.models.event import ExecutionEvent


logger = get_logger("dsrt.arena.trajectory.builder")


# Event types that represent tool calls
_TOOL_EVENTS = frozenset({
    EventType.TOOL_CALL_STARTED.value,
    EventType.TOOL_CALL_COMPLETED.value,
    EventType.TOOL_CALL_FAILED.value,
    EventType.TOOL_STARTED.value,
    EventType.TOOL_COMPLETED.value,
    EventType.TOOL_FAILED.value,
})

# Event types that represent model calls
_MODEL_EVENTS = frozenset({
    EventType.MODEL_REQUEST_STARTED.value,
    EventType.MODEL_REQUEST_COMPLETED.value,
    EventType.MODEL_REQUEST_FAILED.value,
    EventType.MODEL_REQUEST_CREATED.value,
})

# Event types that represent state changes
_STATE_EVENTS = frozenset({
    EventType.WORLD_STATE_CHANGED.value,
    EventType.STATE_PATCH_APPLIED.value,
    EventType.STATE_CONFLICT_DETECTED.value,
})

# Event types that represent failures
_FAILURE_EVENTS = frozenset({
    EventType.EXECUTION_FAILED.value,
    EventType.AGENT_EXECUTION_FAILED.value,
    EventType.MODEL_REQUEST_FAILED.value,
    EventType.TOOL_CALL_FAILED.value,
    EventType.TOOL_FAILED.value,
    EventType.NODE_FAILED.value,
    EventType.VERIFICATION_FAILED.value,
    EventType.WORLD_FAILURE.value,
})

# Event types that represent recovery
_RECOVERY_EVENTS = frozenset({
    EventType.NODE_RETRIED.value,
    EventType.NODE_REASSIGNED.value,
    EventType.MODEL_FALLBACK_COMPLETED.value,
    EventType.CHECKPOINT_RESTORED.value,
})


class TrajectoryBuilder:
    """Builds Arena trajectories from C1 execution events (C8 §16-19).

    Usage:
        builder = TrajectoryBuilder(event_repo)
        events = await event_repo.list_by_execution("exe_1")
        trajectory_events, summary = builder.build(events, config_hash="abc123")
    """

    def __init__(
        self,
        event_repo: EventRepository | None = None,
    ) -> None:
        self._event_repo = event_repo

    def build(
        self,
        execution_events: list[ExecutionEvent],
        *,
        arena_run_id: str,
        configuration_hash: str = "",
        agent_version: str | None = None,
        model_version: str | None = None,
        world_version: str | None = None,
    ) -> tuple[list[TrajectoryEvent], dict[str, Any]]:
        """Build normalized trajectory events from raw execution events.

        Args:
            execution_events: Raw C1 ExecutionEvent records (ordered by sequence).
            arena_run_id: The Arena run this trajectory belongs to.
            configuration_hash: Full configuration fingerprint (C8 §43).
            agent_version: Agent version for this run.
            model_version: Model version for this run.
            world_version: World version for this run.

        Returns:
            (trajectory_events, summary_dict)
        """
        trajectory_events: list[TrajectoryEvent] = []
        tool_call_count = 0
        model_call_count = 0
        failure_count = 0
        recovery_count = 0
        state_change_count = 0

        for event in execution_events:
            # Normalize the event
            te = self._normalize_event(
                event,
                agent_version=agent_version,
                model_version=model_version,
                world_version=world_version,
            )
            trajectory_events.append(te)

            # Count by category
            et = event.event_type
            if et in _TOOL_EVENTS and "STARTED" in et:
                tool_call_count += 1
            elif et in _MODEL_EVENTS and "STARTED" in et:
                model_call_count += 1
            elif et in _FAILURE_EVENTS:
                failure_count += 1
            elif et in _RECOVERY_EVENTS:
                recovery_count += 1
            elif et in _STATE_EVENTS:
                state_change_count += 1

        # Compute summary
        timestamps = [
            e.timestamp for e in execution_events if e.timestamp
        ]
        duration_ms = 0
        start_hash = ""
        final_hash = ""

        if timestamps:
            first = min(timestamps)
            last = max(timestamps)
            duration_ms = int((last - first).total_seconds() * 1000)

        if execution_events:
            start_hash = content_hash(str(execution_events[0].payload))
            final_hash = content_hash(str(execution_events[-1].payload))

        summary = {
            "arena_run_id": arena_run_id,
            "event_count": len(trajectory_events),
            "tool_call_count": tool_call_count,
            "model_call_count": model_call_count,
            "failure_count": failure_count,
            "recovery_count": recovery_count,
            "state_change_count": state_change_count,
            "duration_ms": duration_ms,
            "start_state_hash": start_hash,
            "final_state_hash": final_hash,
            "configuration_hash": configuration_hash,
        }

        logger.info(
            "trajectory_built",
            arena_run_id=arena_run_id,
            events=len(trajectory_events),
            tools=tool_call_count,
            models=model_call_count,
            failures=failure_count,
            duration_ms=duration_ms,
        )

        return trajectory_events, summary

    def _normalize_event(
        self,
        event: ExecutionEvent,
        *,
        agent_version: str | None = None,
        model_version: str | None = None,
        world_version: str | None = None,
    ) -> TrajectoryEvent:
        """Normalize a C1 ExecutionEvent into a C8 TrajectoryEvent (C8 §19).

        Extracts structured fields from the event payload without
        duplicating sensitive content.
        """
        payload = event.payload or {}

        # Extract tool info
        tool_slug = payload.get("tool_slug") or payload.get("tool")
        target = payload.get("target") or payload.get("url")

        # Extract latency and cost
        latency_ms = payload.get("latency_ms") or payload.get("duration_ms")
        tokens = payload.get("tokens") or payload.get("total_tokens")
        cost = payload.get("cost") or payload.get("estimated_cost")

        # Extract error info
        error = payload.get("error") or payload.get("error_code")

        # Extract node info
        node_id = (
            payload.get("node_key")
            or payload.get("node_id")
            or payload.get("node_execution_id")
        )

        # Sanitize payload — remove large content, keep metadata
        sanitized_payload = self._sanitize_payload(payload)

        timestamp_str = (
            event.timestamp.isoformat()
            if event.timestamp
            else datetime.now(timezone.utc).isoformat()
        )

        return TrajectoryEvent(
            event_id=event.id,
            sequence=event.sequence,
            timestamp=timestamp_str,
            event_type=event.event_type,
            source=event.source,
            agent_version=agent_version,
            model_version=model_version,
            world_version=world_version,
            node_id=node_id,
            tool_slug=tool_slug,
            target=target,
            latency_ms=latency_ms,
            tokens=tokens,
            cost_usd=cost,
            error=str(error) if error else None,
            payload=sanitized_payload,
        )

    @staticmethod
    def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
        """Remove large or sensitive content from payload (C8 §19).

        Keeps metadata and references, removes raw content.
        """
        sanitized = {}
        skip_keys = {
            "content", "output", "response", "body",
            "extracted_content", "report", "full_text",
        }

        for key, value in payload.items():
            if key in skip_keys:
                # Replace with a reference indicator
                if isinstance(value, str):
                    sanitized[key] = f"<redacted:{len(value)} chars>"
                elif isinstance(value, dict):
                    sanitized[key] = f"<redacted:dict with {len(value)} keys>"
                else:
                    sanitized[key] = "<redacted>"
            elif isinstance(value, str) and len(value) > 1000:
                sanitized[key] = f"<truncated:{len(value)} chars>"
            else:
                sanitized[key] = value

        return sanitized

    async def build_from_execution(
        self,
        execution_id: str,
        *,
        arena_run_id: str,
        configuration_hash: str = "",
        agent_version: str | None = None,
        model_version: str | None = None,
        world_version: str | None = None,
        limit: int = 10000,
    ) -> tuple[list[TrajectoryEvent], dict[str, Any]]:
        """Convenience method: load events from DB and build trajectory.

        Args:
            execution_id: The C1 execution to build a trajectory from.
            arena_run_id: The Arena run ID.
            configuration_hash: Full config fingerprint.
            limit: Maximum events to load (safety limit).

        Returns:
            (trajectory_events, summary)
        """
        if not self._event_repo:
            raise RuntimeError("EventRepository required for build_from_execution.")

        events = await self._event_repo.list_by_execution(
            execution_id, limit=limit,
        )

        return self.build(
            events,
            arena_run_id=arena_run_id,
            configuration_hash=configuration_hash,
            agent_version=agent_version,
            model_version=model_version,
            world_version=world_version,
        )