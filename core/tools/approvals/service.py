"""
Approval Service — Human-in-the-Loop Authorization (C3 §15, §49).

Manages the lifecycle of approval requests for HIGH/CRITICAL risk
tool actions and EXTERNAL_ACTION/IRREVERSIBLE side effects.

Architecture:
    ToolRouter raises ToolApprovalRequiredError
        ↓
    ToolSDKImpl catches → calls ApprovalService.create_request()
        ↓
    ApprovalRequest record created in DB (status=REQUESTED)
        ↓
    Human reviews via REST API
        ↓
    ApprovalService.decide() → GRANTED / REJECTED
        ↓
    Agent retries tool call (if GRANTED, pre-approved for this request)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from core.api.errors.exceptions import AuthorizationError, NotFoundError, ValidationError
from core.observability.logging import get_logger
from core.repositories.approval_repository import ApprovalRepository
from core.security.context import SecurityContext
from core.storage.models.approval import ApprovalDecisionORM, ApprovalRequestORM
from schemas.domain.enums import ApprovalStatus, OrganizationRole


logger = get_logger("dsrt.tools.approvals")

# Role hierarchy for approval authorization
_ROLE_RANK: dict[str, int] = {
    "viewer": 1,
    "member": 2,
    "admin": 3,
    "owner": 4,
}


class ApprovalService:
    """Central service for managing tool execution approvals."""

    def __init__(self, repo: ApprovalRepository) -> None:
        self._repo = repo

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
        expires_in_seconds: int = 300,
        arguments_preview: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalRequestORM:
        """Create a new approval request for a tool execution.

        Returns the persisted ApprovalRequestORM with its generated ID.
        """
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)

        request = await self._repo.create_request(
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
            expires_at=expires_at,
            arguments_preview=arguments_preview,
            metadata=metadata,
        )

        logger.info(
            "approval_request_created",
            approval_id=request.id,
            tool_slug=tool_slug,
            risk_level=risk_level,
            side_effect=side_effect,
            required_role=required_role,
            expires_at=expires_at.isoformat(),
        )

        return request

    async def decide(
        self,
        *,
        approval_request_id: str,
        decision: str,
        decided_by_user_id: str,
        decided_by_role: str,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalDecisionORM:
        """Record a human decision on an approval request.

        Args:
            approval_request_id: The ID of the approval request.
            decision: Must be "GRANTED" or "REJECTED".
            decided_by_user_id: The user making the decision.
            decided_by_role: The user's role in the organization.
            reason: Optional human-provided reason.

        Returns:
            The persisted ApprovalDecisionORM.

        Raises:
            NotFoundError: If the approval request doesn't exist.
            ValidationError: If the request is already decided or expired.
            AuthorizationError: If the user's role is insufficient.
        """
        # 1. Validate decision value
        if decision not in ("GRANTED", "REJECTED"):
            raise ValidationError(
                f"Decision must be 'GRANTED' or 'REJECTED', got '{decision}'."
            )

        # 2. Fetch the approval request
        request = await self._repo.get_request_by_id(approval_request_id)
        if not request:
            raise NotFoundError(
                f"Approval request '{approval_request_id}' not found."
            )

        # 3. Check if already decided
        if request.status in ("GRANTED", "REJECTED", "EXPIRED", "CANCELLED"):
            raise ValidationError(
                f"Approval request is already '{request.status}'. Cannot decide again."
            )

        # 4. Check expiry
        if request.expires_at and request.expires_at <= datetime.now(timezone.utc):
            await self._repo.update_status(request, "EXPIRED")
            raise ValidationError(
                "Approval request has expired."
            )

        # 5. Check role authorization
        required_rank = _ROLE_RANK.get(request.required_role, 2)
        user_rank = _ROLE_RANK.get(decided_by_role, 0)
        if user_rank < required_rank:
            raise AuthorizationError(
                f"Decision requires role '{request.required_role}' or higher. "
                f"User has role '{decided_by_role}'.",
                metadata={
                    "required_role": request.required_role,
                    "user_role": decided_by_role,
                },
            )

        # 6. Create the decision record
        decision_orm = await self._repo.create_decision(
            approval_request_id=approval_request_id,
            decided_by_user_id=decided_by_user_id,
            decision=decision,
            reason=reason,
            metadata=metadata,
        )

        # 7. Update request status
        await self._repo.update_status(request, decision)

        logger.info(
            "approval_decision_recorded",
            approval_id=approval_request_id,
            decision=decision,
            decided_by=decided_by_user_id,
            tool_slug=request.tool_slug,
        )

        return decision_orm

    async def get_request(
        self, approval_request_id: str,
    ) -> ApprovalRequestORM:
        """Get an approval request by ID."""
        request = await self._repo.get_request_by_id(approval_request_id)
        if not request:
            raise NotFoundError(
                f"Approval request '{approval_request_id}' not found."
            )
        return request

    async def list_pending(
        self,
        organization_id: str,
        limit: int = 50,
    ) -> list[ApprovalRequestORM]:
        """List pending approval requests for an organization."""
        return await self._repo.list_pending(organization_id, limit=limit)

    async def is_approved(
        self,
        tool_slug: str,
        tool_version: str,
        execution_id: str,
    ) -> bool:
        """Check if there's an active GRANTED approval for this tool + execution.

        Used by the ToolSDKImpl to skip re-routing on retry after approval.
        """
        requests = await self._repo.list_by_execution(execution_id)
        for req in requests:
            if (
                req.tool_slug == tool_slug
                and req.tool_version == tool_version
                and req.status == "GRANTED"
            ):
                # Verify not expired
                if req.expires_at and req.expires_at > datetime.now(timezone.utc):
                    return True
                elif not req.expires_at:
                    return True
        return False

    async def expire_stale(self) -> int:
        """Expire all stale approval requests. Returns count expired."""
        count = await self._repo.expire_stale_requests()
        if count > 0:
            logger.info("approval_requests_expired", count=count)
        return count