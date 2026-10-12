"""Unit tests for domain schemas."""

import pytest
from pydantic import ValidationError

from schemas.domain import (
    AgentIdentity,
    AgentManifest,
    ArtifactType,
    CapabilityCreate,
    EventType,
    ExecutionEventCreate,
    ExecutionStatus,
    OrganizationCreate,
    RiskLevel,
    ResourceLimits,
    TaskConstraints,
    TaskCreate,
    UserCreate,
)


class TestOrganizationSchemas:
    def test_organization_create_valid(self):
        org = OrganizationCreate(name="Acme Corp", slug="acme-corp")
        assert org.name == "Acme Corp"
        assert org.slug == "acme-corp"

    def test_organization_slug_rejects_uppercase(self):
        with pytest.raises(ValidationError):
            OrganizationCreate(name="Acme", slug="Acme-Corp")

    def test_organization_slug_rejects_special_chars(self):
        with pytest.raises(ValidationError):
            OrganizationCreate(name="Acme", slug="acme_corp!")


class TestUserSchemas:
    def test_user_create_valid(self):
        user = UserCreate(
            email="alice@example.com",
            display_name="Alice",
            password="a-strong-password",
        )
        assert user.email == "alice@example.com"

    def test_user_rejects_invalid_email(self):
        with pytest.raises(ValidationError):
            UserCreate(email="not-an-email", display_name="X", password="password123")

    def test_user_rejects_short_password(self):
        with pytest.raises(ValidationError):
            UserCreate(email="a@b.co", display_name="X", password="short")


class TestCapabilitySchemas:
    def test_capability_create_valid(self):
        cap = CapabilityCreate(
            slug="research_planning",
            name="Research Planning",
            description="Plans research approaches",
            version="1.0.0",
        )
        assert cap.risk_level == RiskLevel.LOW

    def test_capability_rejects_invalid_slug(self):
        with pytest.raises(ValidationError):
            CapabilityCreate(
                slug="Research Planning",
                name="X", description="Y", version="1.0",
            )

    def test_capability_rejects_invalid_version(self):
        with pytest.raises(ValidationError):
            CapabilityCreate(
                slug="research_planning",
                name="X", description="Y", version="not-a-version",
            )


class TestAgentManifest:
    def _valid_manifest_dict(self) -> dict:
        return {
            "identity": {
                "id": "research_intelligence",
                "name": "Research Intelligence Agent",
                "version": "1.0.0",
                "contract_version": "1.0",
                "publisher": "dsrt",
                "category": "research",
            },
            "capabilities": [
                "research_planning",
                "source_analysis",
                "evidence_synthesis",
            ],
            "requirements": {
                "minimum_core_version": "1.0",
                "required_capabilities": ["model.generate", "artifact.create"],
                "optional_capabilities": ["memory.retrieve"],
                "required_tools": [],
                "optional_tools": [],
            },
            "permissions": {
                "network": {"required": True},
                "filesystem": {"access": "workspace"},
                "browser": {"access": False},
                "external_actions": {"access": False},
            },
        }

    def test_manifest_valid(self):
        m = AgentManifest(**self._valid_manifest_dict())
        assert m.identity.id == "research_intelligence"
        assert len(m.capabilities) == 3

    def test_manifest_rejects_empty_capabilities(self):
        data = self._valid_manifest_dict()
        data["capabilities"] = []
        with pytest.raises(ValidationError):
            AgentManifest(**data)

    def test_manifest_rejects_bad_identity(self):
        data = self._valid_manifest_dict()
        data["identity"]["version"] = "1.0"
        with pytest.raises(ValidationError):
            AgentManifest(**data)

    def test_manifest_rejects_extra_fields(self):
        data = self._valid_manifest_dict()
        data["identity"]["hacker_field"] = "oops"
        with pytest.raises(ValidationError):
            AgentManifest(**data)


class TestTaskSchemas:
    def test_task_create_valid(self):
        task = TaskCreate(
            agent_slug="research_intelligence",
            objective="Investigate X",
        )
        assert task.objective == "Investigate X"

    def test_task_constraints_rejects_negative(self):
        with pytest.raises(ValidationError):
            TaskConstraints(max_duration_seconds=-1)


class TestExecutionSchemas:
    def test_resource_limits_valid(self):
        limits = ResourceLimits(
            max_duration_seconds=1800,
            max_model_calls=100,
            max_tool_calls=500,
            max_storage_mb=500,
        )
        assert limits.max_duration_seconds == 1800

    def test_execution_status_enum(self):
        assert ExecutionStatus.QUEUED.value == "QUEUED"
        assert ExecutionStatus.RUNNING.value == "RUNNING"
        assert ExecutionStatus.COMPLETED.value == "COMPLETED"


class TestEventSchemas:
    def test_event_create_valid(self):
        event = ExecutionEventCreate(
            event_type=EventType.MODEL_REQUEST_STARTED,
            source="model_gateway",
            payload={"model": "gpt-x"},
        )
        assert event.event_type == EventType.MODEL_REQUEST_STARTED

    def test_event_allows_custom_event_type_string(self):
        event = ExecutionEventCreate(
            event_type="RESEARCH_PLAN_CREATED",
            source="research_agent",
        )
        assert event.event_type == "RESEARCH_PLAN_CREATED"


class TestArtifactEnum:
    def test_artifact_types_exist(self):
        assert ArtifactType.DOCUMENT.value == "DOCUMENT"
        assert ArtifactType.CODE.value == "CODE"
        assert ArtifactType.DATASET.value == "DATASET"