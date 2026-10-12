"""Verification schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from schemas.domain.base import DSRTSchema, TimestampedSchema
from schemas.domain.enums import VerificationStatus


class VerificationRequest(DSRTSchema):
    subject_type: str = Field(min_length=1, max_length=50)
    subject_id: str = Field(min_length=1, max_length=32)
    policy_id: str = Field(min_length=1, max_length=200)


class VerificationCheck(DSRTSchema):
    check_type: str
    status: VerificationStatus
    summary: str = ""
    details: dict = Field(default_factory=dict)
    evidence_refs: list = Field(default_factory=list)


class VerificationResult(DSRTSchema):
    id: str
    verification_run_id: str
    check_type: str
    status: VerificationStatus
    summary: str
    details: dict
    evidence_refs: list


class VerificationRun(TimestampedSchema):
    id: str
    execution_id: str
    subject_type: str
    subject_id: str
    policy_id: str
    status: VerificationStatus
    engine_version: str
    started_at: datetime | None
    completed_at: datetime | None
    results: list[VerificationResult] = Field(default_factory=list)