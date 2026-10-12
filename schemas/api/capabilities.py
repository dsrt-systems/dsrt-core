"""API schemas for /capabilities endpoints."""

from __future__ import annotations

from schemas.domain.base import DSRTSchema
from schemas.domain.capability import Capability, CapabilityCreate


class CapabilityListResponse(DSRTSchema):
    capabilities: list[Capability]
    total: int