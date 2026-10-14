"""
Reliability Incident Manager (C6 §36-37).

Manages the full lifecycle of reliability incidents:
  - Creation with classification and severity
  - Resolution tracking
  - Incident history per execution
  - Statistics and reporting

Incident Lifecycle:
    Detected → Classified → Recovery Initiated → Resolved
                         → Escalated (if recovery fails)

Each incident is an immutable record of what went wrong.
Resolution updates the status but preserves the original record.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import (
    EventType,
    IncidentCategory,
    IncidentSeverity,
    VerificationAction,
)

from core.kernel.kernel import ExecutionKernel
from core.observability.logging import get_logger
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.reliability import ReliabilityIncidentORM


logger = get_logger("dsrt.verification.reliability")


class IncidentManager:
    """Manages reliability incident lifecycle (C6 §36).

    Usage:
        mgr = IncidentManager(session, kernel)
        incident = await mgr.create_incident(
            execution_id="exe_1",
            category=IncidentCategory.ARTIFACT,
            severity=IncidentSeverity.HIGH,
            description="Artifact checksum mismatch",
            detected_by="verification_engine",
        )
        await mgr.resolve_incident(incident.id, action="REGENERATE")
    """

    def __init__(
        self,
        session: AsyncSession,
        kernel: ExecutionKernel | None = None,
    ) -> None:
        self._session = session
        self._kernel = kernel

    async def create_incident(
        self,
        *,
        execution_id: str,
        category: IncidentCategory | str,
        severity: IncidentSeverity | str,
        description: str,
        detected_by: str = "verification_engine",
        node_execution_id: str | None = None,
        recovery_action: VerificationAction | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ReliabilityIncidentORM:
        """Create a new reliability incident (C6 §36).

        Args:
            execution_id: The execution where the incident occurred.
            category: One of the 13 incident categories (C6 §37).
            severity: LOW, MEDIUM, HIGH, or CRITICAL.
            description: Human-readable description of the incident.
            detected_by: Component that detected the incident.
            node_execution_id: Specific node that failed (if applicable).
            recovery_action: Recommended recovery action (if known).
            metadata: Additional context about the incident.

        Returns:
            The persisted ReliabilityIncidentORM.
        """
        cat_value = (
            category.value
            if isinstance(category, IncidentCategory)
            else category
        )
        sev_value = (
            severity.value
            if isinstance(severity, IncidentSeverity)
            else severity
        )
        action_value = (
            recovery_action.value
            if isinstance(recovery_action, VerificationAction)
            else recovery_action
        )

        incident = ReliabilityIncidentORM(
            id=new_id(IdPrefix.RELIABILITY_INCIDENT),
            execution_id=execution_id,
            node_execution_id=node_execution_id,
            category=cat_value,
            severity=sev_value,
            description=description,
            detected_by=detected_by,
            recovery_action=action_value,
            resolved=False,
            metadata_json=metadata or {},
        )
        self._session.add(incident)
        await self._session.flush()

        # Emit event
        await self._emit_event(
            execution_id,
            EventType.AGENT_EVENT,
            {
                "reliability_event": "RELIABILITY_INCIDENT_CREATED",
                "incident_id": incident.id,
                "category": cat_value,
                "severity": sev_value,
                "node_execution_id": node_execution_id,
            },
        )

        logger.warning(
            "reliability_incident_created",
            incident_id=incident.id,
            execution_id=execution_id,
            category=cat_value,
            severity=sev_value,
            description=description[:100],
        )

        return incident

    async def resolve_incident(
        self,
        incident_id: str,
        action: str | None = None,
        notes: str = "",
    ) -> ReliabilityIncidentORM | None:
        """Mark an incident as resolved (C6 §36).

        Args:
            incident_id: The incident to resolve.
            action: The recovery action that was taken.
            notes: Human-readable resolution notes.

        Returns:
            The updated incident, or None if not found.
        """
        incident = await self.get_incident(incident_id)
        if not incident:
            return None

        incident.resolved = True
        incident.resolved_at = datetime.now(timezone.utc)
        if action:
            incident.recovery_action = action

        # Append resolution notes to metadata
        meta = dict(incident.metadata_json or {})
        meta["resolution_notes"] = notes
        meta["resolved_at"] = incident.resolved_at.isoformat()
        incident.metadata_json = meta

        await self._session.flush()

        # Emit event
        await self._emit_event(
            incident.execution_id,
            EventType.AGENT_EVENT,
            {
                "reliability_event": "RECOVERY_COMPLETED",
                "incident_id": incident_id,
                "action": action,
            },
        )

        logger.info(
            "reliability_incident_resolved",
            incident_id=incident_id,
            action=action,
        )

        return incident

    async def get_incident(
        self, incident_id: str,
    ) -> ReliabilityIncidentORM | None:
        """Get an incident by ID."""
        stmt = select(ReliabilityIncidentORM).where(
            ReliabilityIncidentORM.id == incident_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_incidents_for_execution(
        self,
        execution_id: str,
        resolved: bool | None = None,
        category: str | None = None,
        limit: int = 100,
    ) -> list[ReliabilityIncidentORM]:
        """List incidents for an execution with optional filters."""
        stmt = select(ReliabilityIncidentORM).where(
            ReliabilityIncidentORM.execution_id == execution_id,
        )
        if resolved is not None:
            stmt = stmt.where(
                ReliabilityIncidentORM.resolved == resolved,
            )
        if category:
            stmt = stmt.where(
                ReliabilityIncidentORM.category == category,
            )
        stmt = stmt.order_by(
            ReliabilityIncidentORM.created_at.desc(),
        ).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_execution_reliability_summary(
        self,
        execution_id: str,
    ) -> dict[str, Any]:
        """Get a reliability summary for an execution.

        Returns counts by category, severity, and resolution status.
        """
        # Total incidents
        total_stmt = select(func.count(ReliabilityIncidentORM.id)).where(
            ReliabilityIncidentORM.execution_id == execution_id,
        )
        total_result = await self._session.execute(total_stmt)
        total = total_result.scalar() or 0

        # Unresolved count
        unresolved_stmt = select(func.count(ReliabilityIncidentORM.id)).where(
            ReliabilityIncidentORM.execution_id == execution_id,
            ReliabilityIncidentORM.resolved == False,
        )
        unresolved_result = await self._session.execute(unresolved_stmt)
        unresolved = unresolved_result.scalar() or 0

        # By category
        cat_stmt = (
            select(
                ReliabilityIncidentORM.category,
                func.count(ReliabilityIncidentORM.id),
            )
            .where(ReliabilityIncidentORM.execution_id == execution_id)
            .group_by(ReliabilityIncidentORM.category)
        )
        cat_result = await self._session.execute(cat_stmt)
        by_category = {row[0]: row[1] for row in cat_result.all()}

        # By severity
        sev_stmt = (
            select(
                ReliabilityIncidentORM.severity,
                func.count(ReliabilityIncidentORM.id),
            )
            .where(ReliabilityIncidentORM.execution_id == execution_id)
            .group_by(ReliabilityIncidentORM.severity)
        )
        sev_result = await self._session.execute(sev_stmt)
        by_severity = {row[0]: row[1] for row in sev_result.all()}

        return {
            "execution_id": execution_id,
            "total_incidents": total,
            "unresolved_incidents": unresolved,
            "resolved_incidents": total - unresolved,
            "by_category": by_category,
            "by_severity": by_severity,
            "reliability_score": (
                round((total - unresolved) / total, 3) if total > 0 else 1.0
            ),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _emit_event(
        self,
        execution_id: str,
        event_type: EventType,
        payload: dict[str, Any],
    ) -> None:
        if not self._kernel:
            return
        try:
            await self._kernel.emit_event(
                execution_id=execution_id,
                event_type=event_type,
                source="dsrt.verification.reliability",
                payload=payload,
            )
        except Exception as e:
            logger.warning(
                "reliability_event_emission_failed",
                execution_id=execution_id,
                error=str(e),
            )