"""
Policy & Strategy Approval Workflow Manager for Phase C11.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ApprovalRequest(BaseModel):
    request_id: str
    tenant_id: str
    change_type: str  # e.g., "fixed_model_lock", "budget_override", "candidate_promotion"
    requested_by: str
    details: Dict = Field(default_factory=dict)
    status: ApprovalStatus = ApprovalStatus.PENDING
    reviewer_comments: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reviewed_at: Optional[datetime] = None


class ApprovalWorkflowManager:
    """
    Handles workflow transitions for policy and optimization override approvals.
    """

    def __init__(self):
        self._requests: Dict[str, ApprovalRequest] = {}

    def create_request(
        self, tenant_id: str, change_type: str, requested_by: str, details: Dict
    ) -> ApprovalRequest:
        req_id = f"appr_{len(self._requests) + 1:04d}"
        req = ApprovalRequest(
            request_id=req_id,
            tenant_id=tenant_id,
            change_type=change_type,
            requested_by=requested_by,
            details=details,
        )
        self._requests[req_id] = req
        return req

    def review_request(
        self, request_id: str, approve: bool, comments: str = ""
    ) -> Optional[ApprovalRequest]:
        req = self._requests.get(request_id)
        if not req:
            return None
        req.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
        req.reviewer_comments = comments
        req.reviewed_at = datetime.now(timezone.utc)
        return req

    def list_pending_requests(self, tenant_id: Optional[str] = None) -> List[ApprovalRequest]:
        reqs = list(self._requests.values())
        if tenant_id:
            reqs = [r for r in reqs if r.tenant_id == tenant_id]
        return [r for r in reqs if r.status == ApprovalStatus.PENDING]