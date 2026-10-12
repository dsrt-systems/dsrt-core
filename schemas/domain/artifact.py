"""
Artifact schemas.
"""

from __future__ import annotations

from pydantic import AliasChoices, Field

from schemas.domain.base import DSRTSchema, TimestampedSchema
from schemas.domain.enums import ArtifactType


class ArtifactCreate(DSRTSchema):
    name: str = Field(min_length=1, max_length=500)
    artifact_type: ArtifactType
    mime_type: str = Field(default="application/octet-stream", max_length=200)
    content: bytes | str
    provenance: dict = Field(default_factory=dict)
    metadata: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("artifact_metadata", "metadata"),
    )


class Artifact(TimestampedSchema):
    id: str
    organization_id: str
    execution_id: str
    task_id: str
    name: str
    artifact_type: ArtifactType
    mime_type: str
    storage_reference: str
    size_bytes: int
    content_hash: str
    provenance: dict
    metadata: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("artifact_metadata", "metadata"),
    )