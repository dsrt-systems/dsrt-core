# Path: core/execution/observability/artifacts.py
"""
Execution Artifact Integration & Storage Manager.
Handles creation, hashing, storage, and tenant isolation for outputs and artifacts.
"""

import os
import hashlib
import json
import uuid
import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class ArtifactType(str, Enum):
    """Supported execution artifact classifications."""

    TEXT = "text"
    JSON = "json"
    CODE = "code"
    PATCH = "patch"
    IMAGE = "image"
    BINARY = "binary"
    LOG = "log"
    REPORT = "report"


class ArtifactRecord(BaseModel):
    """Metadata model representing a stored artifact."""

    artifact_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workspace_id: str
    execution_id: Optional[str] = None
    experiment_id: Optional[str] = None
    name: str
    artifact_type: ArtifactType
    file_path: str
    mime_type: str = "text/plain"
    size_bytes: int = 0
    sha256_hash: str = ""
    metadata_json: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))


class ArtifactManager:
    """Manages workspace-isolated execution artifact persistence and content hashing."""

    def __init__(self, storage_root: str = "./storage/artifacts"):
        self.storage_root = storage_root
        self._records: Dict[str, ArtifactRecord] = {}

    def _ensure_dir(self, workspace_id: str) -> str:
        workspace_dir = os.path.join(self.storage_root, workspace_id)
        os.makedirs(workspace_dir, exist_ok=True)
        return workspace_dir

    def store_artifact(
        self,
        workspace_id: str,
        name: str,
        content: Union[str, bytes],
        artifact_type: ArtifactType = ArtifactType.TEXT,
        execution_id: Optional[str] = None,
        experiment_id: Optional[str] = None,
        mime_type: str = "text/plain",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArtifactRecord:
        """Persists content to storage, calculates SHA-256 hash, and indexes metadata."""
        workspace_dir = self._ensure_dir(workspace_id)
        artifact_id = str(uuid.uuid4())
        filename = f"{artifact_id}_{name}"
        file_path = os.path.join(workspace_dir, filename)

        if isinstance(content, str):
            raw_bytes = content.encode("utf-8")
        else:
            raw_bytes = content

        sha256_hash = hashlib.sha256(raw_bytes).hexdigest()
        size_bytes = len(raw_bytes)

        # Write content to local file system
        with open(file_path, "wb") as f:
            f.write(raw_bytes)

        record = ArtifactRecord(
            artifact_id=artifact_id,
            workspace_id=workspace_id,
            execution_id=execution_id,
            experiment_id=experiment_id,
            name=name,
            artifact_type=artifact_type,
            file_path=file_path,
            mime_type=mime_type,
            size_bytes=size_bytes,
            sha256_hash=sha256_hash,
            metadata_json=metadata or {},
        )
        self._records[artifact_id] = record
        return record

    def get_artifact(self, artifact_id: str, requesting_workspace_id: str) -> Optional[ArtifactRecord]:
        """Retrieves artifact record with tenant workspace validation."""
        record = self._records.get(artifact_id)
        if not record:
            return None
        if record.workspace_id != requesting_workspace_id:
            raise PermissionError(f"Access denied: Workspace '{requesting_workspace_id}' cannot access artifact '{artifact_id}'.")
        return record

    def read_artifact_content(self, artifact_id: str, requesting_workspace_id: str) -> bytes:
        """Reads raw artifact byte content with workspace access validation."""
        record = self.get_artifact(artifact_id, requesting_workspace_id)
        if not record:
            raise FileNotFoundError(f"Artifact '{artifact_id}' not found.")
        
        if not os.path.exists(record.file_path):
            raise FileNotFoundError(f"Physical file missing for artifact '{artifact_id}' at path '{record.file_path}'.")

        with open(record.file_path, "rb") as f:
            return f.read()

    def list_artifacts_for_execution(self, execution_id: str, requesting_workspace_id: str) -> List[ArtifactRecord]:
        """Lists artifacts associated with a specific execution ID."""
        return [
            r for r in self._records.values()
            if r.execution_id == execution_id and r.workspace_id == requesting_workspace_id
        ]