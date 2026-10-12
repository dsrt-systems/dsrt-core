"""Unit tests for Environment Manager and Registry (C3 §33-38)."""

from __future__ import annotations

import uuid
import pytest

from schemas.domain.environment import (
    EnvironmentIdentity,
    EnvironmentManifest,
)
from schemas.domain.enums import EnvironmentType, ProviderType

from core.environments.runtime.base import EnvironmentRuntime
from core.environments.runtime.workspace_runtime import WorkspaceEnvironmentRuntime
from core.repositories import (
    AgentRepository,
    CapabilityRepository,
    EnvironmentRepository,
    ExecutionRepository,
    OrganizationRepository,
    TaskRepository,
    UserRepository,
)
from core.storage.database import db_manager


def _test_manifest(
    slug: str = "test_workspace",
    env_type: EnvironmentType = EnvironmentType.FILE,
) -> EnvironmentManifest:
    return EnvironmentManifest(
        identity=EnvironmentIdentity(
            slug=slug,
            name="Test Workspace",
            version="1.0.0",
            environment_type=env_type,
        ),
        description="Test environment.",
        installed_tools=["filesystem.read", "filesystem.write"],
    )


class TestWorkspaceRuntimeProtocol:
    def test_satisfies_protocol(self):
        runtime = WorkspaceEnvironmentRuntime()
        assert isinstance(runtime, EnvironmentRuntime)
        assert runtime.runtime_type == "FILE"


class TestEnvironmentRegistry:
    @pytest.mark.asyncio
    async def test_register_and_resolve(self):
        from core.environments.registry.registry import EnvironmentRegistry

        suffix = uuid.uuid4().hex[:8]

        async with db_manager.session() as session:
            repo = EnvironmentRepository(session)
            registry = EnvironmentRegistry(repo)

            manifest = _test_manifest(slug=f"test_env_{suffix}")
            version = await registry.register_environment(
                manifest=manifest,
                implementation_class="core.environments.runtime.workspace_runtime:WorkspaceEnvironmentRuntime",
            )
            assert version.version == "1.0.0"

            resolved = await registry.resolve_environment_version(manifest.identity.slug)
            assert resolved.id == version.id


class TestEnvironmentManager:
    @pytest.mark.asyncio
    async def test_provision_and_destroy(self):
        from core.environments.manager.manager import EnvironmentManager
        from core.environments.registry.registry import EnvironmentRegistry

        suffix = uuid.uuid4().hex[:8]

        async with db_manager.session() as session:
            # 1. Seed full database stack to satisfy foreign keys
            org_repo = OrganizationRepository(session)
            user_repo = UserRepository(session)
            org = await org_repo.create(name=f"Org {suffix}", slug=f"org-{suffix}")
            user = await user_repo.create(
                email=f"user-{suffix}@example.com",
                display_name="User",
                password_hash="hash",
            )
            await org_repo.add_member(organization_id=org.id, user_id=user.id, role="owner")

            cap_repo = CapabilityRepository(session)
            agent_repo = AgentRepository(session)
            cap = await cap_repo.create(
                slug=f"cap_{suffix}", name="Cap", description="D", version="1.0.0"
            )
            agent = await agent_repo.create_agent(
                slug=f"agent_{suffix}",
                name="Agent",
                description="D",
                category="test",
                publisher="dsrt",
            )
            agent_ver = await agent_repo.create_agent_version(
                agent_id=agent.id,
                version="1.0.0",
                contract_version="1.0",
                manifest={"identity": {"id": agent.slug, "version": "1.0.0"}},
                package_reference="pkg",
                configuration={},
                requirements={},
                permissions={},
            )
            await agent_repo.link_capability(agent_ver.id, cap.id)

            task_repo = TaskRepository(session)
            exe_repo = ExecutionRepository(session)
            task = await task_repo.create(
                organization_id=org.id,
                user_id=user.id,
                agent_slug=agent.slug,
                objective="Env test",
            )
            execution = await exe_repo.create(
                task_id=task.id,
                organization_id=org.id,
                core_version="1.0.0",
                agent_version_id=agent_ver.id,
                contract_version="1.0",
                configuration_hash="0" * 64,
            )

            # 2. Register Environment Blueprint
            env_repo = EnvironmentRepository(session)
            registry = EnvironmentRegistry(env_repo)
            manager = EnvironmentManager(session, registry=registry)

            manifest = _test_manifest(slug=f"ws_env_{suffix}")
            await registry.register_environment(
                manifest=manifest,
                implementation_class="core.environments.runtime.workspace_runtime:WorkspaceEnvironmentRuntime",
            )

            # 3. Provision environment instance using real org_id and execution_id
            instance = await manager.provision(
                environment_slug=f"ws_env_{suffix}",
                organization_id=org.id,
                execution_id=execution.id,
                task_id=task.id,
            )
            assert instance.status == "READY"
            assert instance.runtime_reference is not None

            # 4. Destroy environment instance
            destroyed = await manager.destroy(instance.id)
            assert destroyed is True