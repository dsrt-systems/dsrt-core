"""Capability schemas."""

from __future__ import annotations

from pydantic import Field

from schemas.domain.base import DSRTSchema, TimestampedSchema
from schemas.domain.enums import RiskLevel


class CapabilityCreate(DSRTSchema):
    slug: str = Field(
        min_length=2,
        max_length=200,
        pattern=r"^[a-z][a-z0-9_.-]*$",  # Added hyphen support
        description="Canonical capability identifier, e.g. 'research_planning' or 'web-search'",
    )
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    version: str = Field(pattern=r"^\d+\.\d+(\.\d+)?$")
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    requirements: dict = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.LOW

class Capability(TimestampedSchema):
    id: str
    slug: str
    name: str
    description: str
    version: str
    input_schema: dict
    output_schema: dict
    requirements: dict
    risk_level: RiskLevel