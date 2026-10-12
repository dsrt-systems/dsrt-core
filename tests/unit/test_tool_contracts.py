"""
C3.1 Contract Tests.

Validates every C3 Pydantic schema and the DSRTTool Protocol are structurally
sound, enforce their invariants, and serialize cleanly.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from core.tools import DSRTTool
from schemas.domain.enums import (
    ApprovalStatus,
    EnvironmentStatus,
    EnvironmentType,
    FilesystemAccessMode,
    NetworkMode,
    ObservationType,
    SideEffectClass,
    ToolExecutionStatus,
    ToolHealthStatus,
    ToolRiskLevel,
    ToolStatus,
    WorldStatus,
)
from schemas.domain.approval import (
    ApprovalCreate,
    ApprovalDecisionCreate,
    ApprovalRequest,
)
from schemas.domain.environment import (
    EnvironmentFilesystemPolicy,
    EnvironmentIdentity,
    EnvironmentManifest,
    EnvironmentNetworkPolicy,
    EnvironmentResourceLimits,
)
from schemas.domain.tool import (
    ToolCapabilityDeclaration,
    ToolContext,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolHealth,
    ToolIdentity,
    ToolInitializationResult,
    ToolLimits,
    ToolManifest,
    ToolObservation,
    ToolPermissionDeclaration,
    ToolRetryPolicy,
    ToolUsage,
)
from schemas.domain.world import (
    WorldIdentity,
    WorldManifest,
    WorldPolicy,
)


# =============================================================================
# Tool identity & manifest
# =============================================================================


class TestToolIdentity:
    def test_valid(self) -> None:
        ident = ToolIdentity(
            slug="web.search",
            name="Web Search",
            version="1.0.0",
            category="web",
        )
        assert ident.slug == "web.search"
        assert ident.contract_version == "1.0"
        assert ident.publisher == "dsrt"

    def test_identity_is_frozen(self) -> None:
        ident = ToolIdentity(
            slug="web.search",
            name="Web Search",
            version="1.0.0",
            category="web",
        )
        with pytest.raises(ValidationError):
            ident.slug = "something.else"  # type: ignore[misc]

    def test_short_slug_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ToolIdentity(
                slug="w",
                name="Web Search",
                version="1.0.0",
                category="web",
            )


class TestToolRetryPolicy:
    def test_non_idempotent_disallows_multiple_attempts(self) -> None:
        with pytest.raises(ValidationError):
            ToolRetryPolicy(
                allowed=True,
                max_attempts=3,
                idempotent=False,
            )

    def test_non_idempotent_single_attempt_ok(self) -> None:
        policy = ToolRetryPolicy(
            allowed=True,
            max_attempts=1,
            idempotent=False,
        )
        assert policy.max_attempts == 1

    def test_idempotent_multiple_attempts_ok(self) -> None:
        policy = ToolRetryPolicy(
            allowed=True,
            max_attempts=5,
            idempotent=True,
        )
        assert policy.max_attempts == 5


class TestToolManifest:
    def test_minimal_manifest(self) -> None:
        manifest = ToolManifest(
            identity=ToolIdentity(
                slug="web.search",
                name="Web Search",
                version="1.0.0",
                category="web",
            ),
            capabilities=[
                ToolCapabilityDeclaration(slug="web.search"),
            ],
        )
        assert manifest.risk_level == ToolRiskLevel.LOW
        assert manifest.side_effect == SideEffectClass.READ
        assert manifest.requires_approval is False

    def test_duplicate_capabilities_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ToolManifest(
                identity=ToolIdentity(
                    slug="web.search",
                    name="Web Search",
                    version="1.0.0",
                    category="web",
                ),
                capabilities=[
                    ToolCapabilityDeclaration(slug="web.search"),
                    ToolCapabilityDeclaration(slug="web.search"),
                ],
            )

    def test_high_risk_external_action_allowed(self) -> None:
        """High-risk external actions are allowed but policy will likely require approval."""
        manifest = ToolManifest(
            identity=ToolIdentity(
                slug="email.send",
                name="Email Sender",
                version="1.0.0",
                category="communication",
            ),
            risk_level=ToolRiskLevel.HIGH,
            side_effect=SideEffectClass.EXTERNAL_ACTION,
            requires_approval=True,
        )
        assert manifest.requires_approval is True


class TestToolExecutionRequest:
    def test_valid(self) -> None:
        req = ToolExecutionRequest(
            request_id="req_01HN8X9K2M3P4Q5R6S7T8V9W0Y",
            tool_slug="web.search",
            execution_id="exe_01HN8X9K2M3P4Q5R6S7T8V9W01",
            task_id="tsk_01HN8X9K2M3P4Q5R6S7T8V9W02",
            organization_id="org_01HN8X9K2M3P4Q5R6S7T8V9W03",
            agent_slug="research_intelligence",
            agent_version="1.0.0",
            arguments={"query": "DSRT"},
        )
        assert req.attempt == 1

    def test_attempt_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            ToolExecutionRequest(
                request_id="req_x",
                tool_slug="web.search",
                execution_id="exe_x",
                task_id="tsk_x",
                organization_id="org_x",
                agent_slug="research_intelligence",
                agent_version="1.0.0",
                arguments={},
                attempt=0,
            )


class TestToolObservation:
    def test_minimal(self) -> None:
        obs = ToolObservation(
            observation_id="obs_01HN8X9K2M3P4Q5R6S7T8V9W0Y",
            observation_type=ObservationType.TEXT,
            timestamp=datetime.now(timezone.utc),
            source="web.search",
        )
        assert obs.observation_type == ObservationType.TEXT
        assert obs.truncated is False

    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            ToolObservation(
                observation_id="obs_x",
                observation_type=ObservationType.TEXT,
                timestamp=datetime.now(timezone.utc),
                confidence=1.5,
            )


class TestToolExecutionResult:
    def test_minimal(self) -> None:
        result = ToolExecutionResult(
            request_id="req_x",
            tool_execution_id="tex_x",
            tool_slug="web.search",
            tool_version="1.0.0",
            status=ToolExecutionStatus.COMPLETED,
            usage=ToolUsage(duration_ms=120),
            duration_ms=120,
        )
        assert result.status == ToolExecutionStatus.COMPLETED
        assert result.observations == []
        assert result.artifact_ids == []


class TestToolHealth:
    def test_minimal(self) -> None:
        health = ToolHealth(
            tool_slug="web.search",
            tool_version="1.0.0",
            status=ToolHealthStatus.HEALTHY,
        )
        assert health.error_rate == 0.0


# =============================================================================
# Environment
# =============================================================================


class TestEnvironmentManifest:
    def test_minimal(self) -> None:
        manifest = EnvironmentManifest(
            identity=EnvironmentIdentity(
                slug="research_workspace",
                name="Research Workspace",
                version="1.0.0",
                environment_type=EnvironmentType.FILE,
            ),
        )
        assert manifest.network.mode == NetworkMode.RESTRICTED
        assert manifest.filesystem.access_mode == FilesystemAccessMode.WORKSPACE

    def test_duplicate_installed_tools_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EnvironmentManifest(
                identity=EnvironmentIdentity(
                    slug="research_workspace",
                    name="Research Workspace",
                    version="1.0.0",
                    environment_type=EnvironmentType.FILE,
                ),
                installed_tools=["web.search", "web.search"],
            )


# =============================================================================
# World
# =============================================================================


class TestWorldManifest:
    def test_minimal(self) -> None:
        manifest = WorldManifest(
            identity=WorldIdentity(
                slug="research_world",
                name="Research World",
                version="1.0.0",
            ),
            exposed_tools=["web.search", "web.retrieve", "filesystem.read"],
            capabilities=["research"],
        )
        assert manifest.policy.network_mode == NetworkMode.CONTROLLED
        assert "research" in manifest.capabilities

    def test_duplicate_exposed_tools_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WorldManifest(
                identity=WorldIdentity(
                    slug="research_world",
                    name="Research World",
                    version="1.0.0",
                ),
                exposed_tools=["web.search", "web.search"],
            )


# =============================================================================
# Approval
# =============================================================================


class TestApprovalRequest:
    def test_minimal(self) -> None:
        req = ApprovalCreate(
            organization_id="org_x",
            execution_id="exe_x",
            tool_execution_id="tex_x",
            tool_slug="email.send",
            tool_version="1.0.0",
            requested_action="Send email to recipient@example.com",
            risk_level=ToolRiskLevel.HIGH,
            side_effect=SideEffectClass.EXTERNAL_ACTION,
        )
        assert req.risk_level == ToolRiskLevel.HIGH


# =============================================================================
# DSRTTool Protocol (runtime-checkable)
# =============================================================================


class _MinimalTool:
    """A minimal structural implementation of DSRTTool used for protocol check."""

    def __init__(self) -> None:
        self.identity = ToolIdentity(
            slug="test.tool",
            name="Test Tool",
            version="1.0.0",
            category="test",
        )
        self.manifest = ToolManifest(
            identity=self.identity,
            capabilities=[ToolCapabilityDeclaration(slug="test.tool")],
        )

    async def initialize(self, context):  # type: ignore[no-untyped-def]
        return ToolInitializationResult(ready=True)

    async def execute(self, request):  # type: ignore[no-untyped-def]
        return ToolExecutionResult(
            request_id=request.request_id,
            tool_execution_id="tex_test",
            tool_slug=request.tool_slug,
            tool_version="1.0.0",
            status=ToolExecutionStatus.COMPLETED,
            usage=ToolUsage(),
            duration_ms=0,
        )

    async def cancel(self, request_id):  # type: ignore[no-untyped-def]
        return None

    async def health(self):  # type: ignore[no-untyped-def]
        return ToolHealth(
            tool_slug="test.tool",
            tool_version="1.0.0",
            status=ToolHealthStatus.HEALTHY,
        )


class TestDSRTToolProtocol:
    def test_structural_conformance(self) -> None:
        tool = _MinimalTool()
        assert isinstance(tool, DSRTTool)

    def test_incomplete_implementation_fails_protocol(self) -> None:
        class _Incomplete:
            identity = ToolIdentity(
                slug="x.y", name="X", version="1.0.0", category="test",
            )
            manifest = ToolManifest(
                identity=ToolIdentity(
                    slug="x.y", name="X", version="1.0.0", category="test",
                ),
            )
            # Missing execute / cancel / health.

            async def initialize(self, context):  # type: ignore[no-untyped-def]
                return ToolInitializationResult(ready=True)

        assert not isinstance(_Incomplete(), DSRTTool)


class TestToolExecutionError:
    def test_minimal(self) -> None:
        from schemas.domain.tool import ToolExecutionError

        err = ToolExecutionError(
            code="TOOL_TIMEOUT",
            message="Tool timed out after 30s",
            retryable=True,
        )
        assert err.code == "TOOL_TIMEOUT"
        assert err.retryable is True

    def test_defaults(self) -> None:
        from schemas.domain.tool import ToolExecutionError

        err = ToolExecutionError(code="X", message="y")
        assert err.retryable is False
        assert err.metadata == {}        