"""
Model Session and Checkpoint Schemas (C2 §40).

Tracks model continuity and handles mid-execution model switching.
"""

from __future__ import annotations

from pydantic import Field

from schemas.domain.base import DSRTSchema, TimestampedSchema


class ModelSessionCreate(DSRTSchema):
    execution_id: str
    model_id: str
    provider_id: str


class ModelSession(TimestampedSchema):
    id: str
    execution_id: str
    model_id: str
    provider_id: str
    status: str  # active, closed, switched


class ModelCheckpointCreate(DSRTSchema):
    session_id: str
    request_id: str
    context_hash: str
    canonical_state_hash: str
    output_hash: str
    metadata: dict = Field(default_factory=dict)


class ModelCheckpoint(TimestampedSchema):
    id: str
    session_id: str
    request_id: str
    context_hash: str
    canonical_state_hash: str
    output_hash: str
    metadata: dict