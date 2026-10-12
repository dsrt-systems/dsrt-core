"""API schemas for /artifacts endpoints."""

from __future__ import annotations

from schemas.domain import Artifact
from schemas.domain.base import DSRTSchema


class ArtifactListResponse(DSRTSchema):
    """Response payload for listing artifacts."""

    artifacts: list[Artifact]
    total: int