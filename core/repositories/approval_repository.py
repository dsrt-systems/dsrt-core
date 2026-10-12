"""
Approval Repository.

Handles persistence for ApprovalRequest and ApprovalDecision records.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from core.repositories.base import Repository
from core.storage.models.approval import ApprovalDecisionORM, ApprovalRequestORM
from core.storage.models.mixins import utcnow


class ApprovalRepository(Repository):
    """Repository for approval lifecycle persistence."""

    # --- Approval Requests ---

    async def create_request(
        self,
        *,
        organization_id: str,
        execution_id: str,
        tool_execution_id: str,
        tool_slug: str,
        tool_version: str,
        requested_action: str,
        risk_level: str,
        side_effect: str,
        required_role: str = "member",
        reason: str = "",
        expires_at: datetime | None = None,
        arguments_preview: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalRequestORM:
        """Create a new approval request."""
        req = ApprovalRequestORM(
            organization_id=organization_id,
            execution_id=execution_id,
            tool_execution_id=tool_execution_id,
            tool_slug=tool_slug,
            tool_version=tool_version,
            requested_action=requested_action,
            risk_level=risk_level,
            side_effect=side_effect,
            required_role=required_role,
            reason=reason,
            status="REQUESTED",
            expires_at=expires_at,
            arguments_preview=arguments_preview or {},
            metadata_json=metadata or {},
        )
        self._session.add(req)
        await self._session.flush()
        return req

    async def get_request_by_id(
        self, request_id: str,
    ) -> ApprovalRequestORM | None:
        """Get an approval request by primary key."""
        stmt = (
            select(ApprovalRequestORM)
            .where(ApprovalRequestORM.id == request_id)
            .options(selectinload(ApprovalRequestORM.decisions))
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_pending(
        self,
        organization_id: str,
        limit: int = 50,
    ) -> list[ApprovalRequestORM]:
        """List pending (undecided) approval requests for an organization."""
        stmt = (
            select(ApprovalRequestORM)
            .where(
                ApprovalRequestORM.organization_id == organization_id,
                ApprovalRequestORM.status.in_(["REQUESTED", "PENDING"]),
            )
            .order_by(ApprovalRequestORM.created_at.desc())
            .limit(limit)
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def list_by_execution(
        self,
        execution_id: str,
        limit: int = 50,
    ) -> list[ApprovalRequestORM]:
        """List all approval requests for a given execution."""
        stmt = (
            select(ApprovalRequestORM)
            .where(ApprovalRequestORM.execution_id == execution_id)
            .order_by(ApprovalRequestORM.created_at.desc())
            .limit(limit)
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def update_status(
        self,
        request: ApprovalRequestORM,
        status: str,
    ) -> ApprovalRequestORM:
        """Update the status of an approval request."""
        request.status = status
        await self._session.flush()
        return request

    async def expire_stale_requests(
        self,
        before: datetime | None = None,
    ) -> int:
        """Expire all requests whose expires_at has passed. Returns count expired."""
        cutoff = before or datetime.now(timezone.utc)
        stmt = (
            update(ApprovalRequestORM)
            .where(
                ApprovalRequestORM.status.in_(["REQUESTED", "PENDING"]),
                ApprovalRequestORM.expires_at.isnot(None),
                ApprovalRequestORM.expires_at <= cutoff,
            )
            .values(status="EXPIRED")
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount

    # --- Approval Decisions ---

    async def create_decision(
        self,
        *,
        approval_request_id: str,
        decided_by_user_id: str,
        decision: str,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalDecisionORM:
        """Record a human decision on an approval request."""
        dec = ApprovalDecisionORM(
            approval_request_id=approval_request_id,
            decided_by_user_id=decided_by_user_id,
            decision=decision,
            reason=reason,
            metadata_json=metadata or {},
        )
        self._session.add(dec)
        await self._session.flush()
        return dec

    async def get_decisions(
        self, approval_request_id: str,
    ) -> list[ApprovalDecisionORM]:
        """Get all decisions for an approval request."""
        stmt = (
            select(ApprovalDecisionORM)
            .where(ApprovalDecisionORM.approval_request_id == approval_request_id)
            .order_by(ApprovalDecisionORM.created_at.desc())
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all())