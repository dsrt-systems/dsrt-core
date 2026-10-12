"""
Base classes for DSRT Pydantic schemas.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DSRTSchema(BaseModel):
    """Base for all DSRT schemas — strict validation."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
        frozen=False,
        populate_by_name=True,
    )


class DSRTImmutableSchema(BaseModel):
    """Frozen variant for contract objects that must not mutate."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )


class TimestampedSchema(DSRTSchema):
    """Adds standard timestamps."""

    created_at: datetime
    updated_at: datetime