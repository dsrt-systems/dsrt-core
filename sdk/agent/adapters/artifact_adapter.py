"""
ArtifactSDK Implementation.

Creates artifacts via the Core artifacts repository. Backing storage is
opaque to agents — C1 stores content_reference as an inline identifier;
real S3/Supabase Storage backends arrive with the full Artifact Fabric.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.kernel.fingerprint import content_hash
from core.observability.logging import get_logger
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models import Artifact
from sdk.agent.interfaces.artifact import SDKArtifact


logger = get_logger("sdk.artifacts")


class ArtifactSDKImpl:
    """Concrete implementation of ArtifactSDK."""

    def __init__(
        self,
        session: AsyncSession,
        execution_id: str,
        task_id: str,
        organization_id: str,
        agent_slug: str,
        agent_version_id: str,
    ) -> None:
        self._session = session
        self._execution_id = execution_id
        self._task_id = task_id
        self._organization_id = organization_id
        self._agent_slug = agent_slug
        self._agent_version_id = agent_version_id

    async def create(
        self,
        name: str,
        artifact_type: str,
        content: bytes | str,
        mime_type: str = "application/octet-stream",
        provenance: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SDKArtifact:
        if isinstance(content, str):
            body = content.encode("utf-8")
        else:
            body = content

        artifact_id = new_id(IdPrefix.ARTIFACT)
        hash_hex = content_hash(body)

        # C1 in-database inline storage. Real object storage lands with the
        # full Artifact Fabric — the SDK contract is stable regardless.
        storage_reference = f"inline://{artifact_id}"

        merged_provenance = {
            "agent_slug": self._agent_slug,
            "agent_version_id": self._agent_version_id,
            "execution_id": self._execution_id,
            **(provenance or {}),
        }

        art = Artifact(
            id=artifact_id,
            organization_id=self._organization_id,
            execution_id=self._execution_id,
            task_id=self._task_id,
            name=name,
            artifact_type=artifact_type,
            mime_type=mime_type,
            storage_reference=storage_reference,
            size_bytes=len(body),
            content_hash=hash_hex,
            provenance=merged_provenance,
            artifact_metadata=metadata or {},
        )
        self._session.add(art)
        await self._session.flush()

        logger.info(
            "artifact_created",
            artifact_id=art.id,
            execution_id=self._execution_id,
            name=name,
            artifact_type=artifact_type,
            size_bytes=len(body),
        )

        return SDKArtifact(
            id=art.id,
            name=art.name,
            artifact_type=art.artifact_type,
            mime_type=art.mime_type,
            size_bytes=art.size_bytes,
            content_hash=art.content_hash,
            metadata=dict(art.artifact_metadata or {}),
        )

    async def get(self, artifact_id: str) -> SDKArtifact | None:
        result = await self._session.execute(
            select(Artifact).where(
                Artifact.id == artifact_id,
                Artifact.execution_id == self._execution_id,
            )
        )
        art = result.scalar_one_or_none()
        if art is None:
            return None
        return SDKArtifact(
            id=art.id,
            name=art.name,
            artifact_type=art.artifact_type,
            mime_type=art.mime_type,
            size_bytes=art.size_bytes,
            content_hash=art.content_hash,
            metadata=dict(art.artifact_metadata or {}),
        )