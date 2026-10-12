"""
Artifact SDK Contract (C1 §25).

Agents create artifacts through Core; storage backend is opaque.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SDKArtifact:
    """Reference to a Core-persisted artifact."""

    id: str
    name: str
    artifact_type: str
    mime_type: str
    size_bytes: int
    content_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ArtifactSDK(Protocol):
    """Artifact SDK — durable output creation."""

    async def create(
        self,
        name: str,
        artifact_type: str,
        content: bytes | str,
        mime_type: str = "application/octet-stream",
        provenance: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SDKArtifact:
        """Create a durable artifact."""
        ...

    async def get(self, artifact_id: str) -> SDKArtifact | None:
        """Fetch artifact metadata by id."""
        ...