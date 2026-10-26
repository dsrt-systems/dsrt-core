"""
Comprehensive C7 World Runtime Tests.

Covers all C7 sub-phases:
  C7.1 Schemas & Enums
  C7.2 Database ORM
  C7.3 Templates & Registry
  C7.4 Runtime & Lifecycle
  C7.5 Components
  C7.6 State & Snapshots
  C7.7 Isolation & Network
  C7.8 SDK & API
  C7.9 C5/C6 Integration
"""

from __future__ import annotations

import asyncio
import pytest

from schemas.domain.enums import (
    EventType,
    NetworkMode,
    WorldActionReversibility,
    WorldChangeType,
    WorldClockMode,
    WorldComponentType,
    WorldSnapshotType,
    WorldStatus,
)
from schemas.domain.world import (
    WorldChange,
    WorldComponentSpec,
    WorldCredentialRef,
    WorldHealth,
    WorldIdentity,
    WorldManifest,
    WorldNetworkPolicy,
    WorldObservation,
    WorldPolicy,
    WorldProvisionRequest,
    WorldResourceLimits,
    WorldSnapshot,
    WorldState,
    WorldStateDiff,
    WorldTemplate,
)


# =====================================================================
# C7.1 — Schemas & Enums
# =====================================================================


class TestC7Schemas:
    def test_world_component_types(self):
        assert len(list(WorldComponentType)) == 11

    def test_world_clock_modes(self):
        assert len(list(WorldClockMode)) == 4
        assert WorldClockMode.FIXED_TIME.value == "fixed_time"

    def test_world_change_types(self):
        assert len(list(WorldChangeType)) == 12
        assert WorldChangeType.FILE_CREATED.value == "FILE_CREATED"

    def test_reversibility(self):
        assert len(list(WorldActionReversibility)) == 3

    def test_snapshot_types(self):
        assert len(list(WorldSnapshotType)) == 3

    def test_c7_event_types(self):
        for e in [
            "WORLD_CREATED", "WORLD_STARTED", "WORLD_PAUSED",
            "WORLD_RESUMED", "WORLD_RESET_COMPLETED",
            "WORLD_SNAPSHOT_COMPLETED", "WORLD_DESTROYED",
            "WORLD_STATE_CHANGED", "WORLD_COMPONENT_STARTED",
        ]:
            assert hasattr(EventType, e)

    def test_world_manifest_extended(self):
        m = WorldManifest(
            identity=WorldIdentity(slug="test", name="T", version="1.0"),
            components=[
                WorldComponentSpec(
                    component_type=WorldComponentType.FILESYSTEM, slug="fs",
                ),
            ],
            services=["postgres"],
            resources=WorldResourceLimits(cpu_limit=8),
            clock_mode=WorldClockMode.FIXED_TIME,
            simulation_date="2026-01-01",
        )
        assert len(m.components) == 1
        assert m.resources.cpu_limit == 8
        assert m.clock_mode == WorldClockMode.FIXED_TIME

    def test_c3_backward_compat(self):
        m = WorldManifest(
            identity=WorldIdentity(slug="old", name="O", version="1.0"),
        )
        assert m.components == []
        assert m.clock_mode == WorldClockMode.REAL_TIME
        assert m.resources.cpu_limit == 4

    def test_world_provision_request(self):
        r = WorldProvisionRequest(
            world_slug="software_engineering_world",
            organization_id="org_1",
        )
        assert r.world_slug == "software_engineering_world"

    def test_world_state_diff(self):
        d = WorldStateDiff(
            world_id="w1", before_snapshot_id="s1",
            after_snapshot_id="s2", changes=[
                WorldChange(
                    change_type=WorldChangeType.FILE_CREATED,
                    component="filesystem", target="/report.md",
                ),
            ],
            total_changes=1,
        )
        assert d.total_changes == 1

    def test_world_credential_ref(self):
        c = WorldCredentialRef(
            credential_ref="credential://github/read",
            provider="github",
        )
        assert c.credential_ref.startswith("credential://")

    def test_world_template(self):
        t = WorldTemplate(
            slug="research_v1",
            name="Research Template",
            base_manifest=WorldManifest(
                identity=WorldIdentity(slug="res", name="Research", version="1.0"),
            ),
        )
        assert t.slug == "research_v1"


# =====================================================================
# C7.2 — Database ORM
# =====================================================================


class TestC7ORM:
    def test_all_orm_models_importable(self):
        from core.storage.models import (
            WorldORM, WorldVersionORM, WorldInstanceORM,
            WorldComponentORM, WorldSnapshotORM,
            WorldStateVersionORM, WorldStateChangeORM,
            WorldNetworkPolicyORM, WorldHealthRecordORM,
        )
        assert WorldORM.__tablename__ == "worlds"
        assert WorldComponentORM.__tablename__ == "world_components"
        assert WorldSnapshotORM.__tablename__ == "world_snapshots"
        assert WorldStateVersionORM.__tablename__ == "world_state_versions"
        assert WorldStateChangeORM.__tablename__ == "world_state_changes"
        assert WorldNetworkPolicyORM.__tablename__ == "world_network_policies"
        assert WorldHealthRecordORM.__tablename__ == "world_health_records"

    def test_world_instance_c7_columns(self):
        from core.storage.models import WorldInstanceORM
        assert hasattr(WorldInstanceORM, "resource_profile")
        assert hasattr(WorldInstanceORM, "clock_mode")
        assert hasattr(WorldInstanceORM, "simulation_date")

    def test_relationships(self):
        from core.storage.models import WorldInstanceORM
        assert hasattr(WorldInstanceORM, "components")
        assert hasattr(WorldInstanceORM, "snapshots")
        assert hasattr(WorldInstanceORM, "state_versions")
        assert hasattr(WorldInstanceORM, "health_records")


# =====================================================================
# C7.3 — Templates
# =====================================================================


class TestC7Templates:
    def test_software_world(self):
        from core.worlds.templates import SOFTWARE_WORLD_MANIFEST
        m = SOFTWARE_WORLD_MANIFEST
        assert m.identity.slug == "software_engineering_world"
        assert "software_engineering" in m.capabilities
        assert len(m.components) == 6
        assert m.snapshot_supported is True

    def test_data_science_world(self):
        from core.worlds.templates import DATA_SCIENCE_WORLD_MANIFEST
        m = DATA_SCIENCE_WORLD_MANIFEST
        assert "data_analysis" in m.capabilities
        assert m.resources.memory_mb == 16384

    def test_research_world_v2(self):
        from core.worlds.templates import RESEARCH_WORLD_V2_MANIFEST
        m = RESEARCH_WORLD_V2_MANIFEST
        assert m.identity.version == "2.0.0"
        assert "evidence_synthesis" in m.capabilities

    def test_c3_research_preserved(self):
        from core.worlds.builtins.research_world import RESEARCH_WORLD_MANIFEST
        assert RESEARCH_WORLD_MANIFEST.identity.version == "1.0.0"
        assert RESEARCH_WORLD_MANIFEST.components == []


# =====================================================================
# C7.4 — Runtime & Lifecycle
# =====================================================================


class TestC7Lifecycle:
    def test_15_world_statuses(self):
        assert len(list(WorldStatus)) == 15

    def test_lifecycle_transitions(self):
        from core.worlds.runtime.lifecycle import WorldLifecycleManager
        lm = WorldLifecycleManager()
        for valid in [
            ("REGISTERED", "VALIDATING"), ("VALIDATING", "READY"),
            ("READY", "PROVISIONING"), ("PROVISIONING", "RUNNING"),
            ("RUNNING", "PAUSING"), ("PAUSING", "PAUSED"),
            ("PAUSED", "RESUMING"), ("RESUMING", "RUNNING"),
            ("RUNNING", "RESETTING"), ("RESETTING", "READY"),
            ("RUNNING", "SNAPSHOTTING"), ("SNAPSHOTTING", "RUNNING"),
            ("RUNNING", "DESTROYING"), ("DESTROYING", "DESTROYED"),
        ]:
            lm.validate_transition(valid[0], valid[1])

    def test_invalid_transitions(self):
        from core.worlds.runtime.lifecycle import WorldLifecycleManager
        lm = WorldLifecycleManager()
        for invalid in [("DESTROYED", "RUNNING"), ("PAUSED", "STARTING")]:
            with pytest.raises(ValueError):
                lm.validate_transition(invalid[0], invalid[1])

    def test_world_manager_methods(self):
        from core.worlds.manager.manager import WorldManager
        for m in ["provision", "start", "pause", "resume", "reset",
                   "snapshot", "destroy", "health", "observe"]:
            assert hasattr(WorldManager, m)


# =====================================================================
# C7.5 — Components
# =====================================================================


class TestC7Components:
    def test_five_component_types(self):
        from core.worlds.components import (
            FilesystemComponent, BrowserComponent, TerminalComponent,
            RuntimeComponent, DatabaseComponent,
        )
        comps = [
            FilesystemComponent(), BrowserComponent(),
            TerminalComponent(), RuntimeComponent(), DatabaseComponent(),
        ]
        types = {c.component_type for c in comps}
        assert types == {"filesystem", "browser", "terminal", "runtime", "database"}

    def test_component_lifecycle(self):
        from core.worlds.components import BrowserComponent, ComponentContext
        br = BrowserComponent()
        ctx = ComponentContext(
            world_instance_id="wi", organization_id="org",
        )
        assert asyncio.run(br.provision(ctx))
        assert asyncio.run(br.start(ctx))
        h = asyncio.run(br.health(ctx))
        assert h.is_healthy
        assert asyncio.run(br.destroy(ctx))

    def test_component_manager(self):
        from core.worlds.components import ComponentManager
        mgr = ComponentManager.__new__(ComponentManager)
        mgr._session = None
        mgr._active_components = {}
        c = mgr.create_component("filesystem", "workspace")
        assert c.component_type == "filesystem"
        with pytest.raises(ValueError):
            mgr.create_component("nonexistent", "x")


# =====================================================================
# C7.6 — State & Snapshots
# =====================================================================


class TestC7State:
    def test_diff_engine(self):
        from core.worlds.state.diffs import WorldDiffEngine
        engine = WorldDiffEngine.__new__(WorldDiffEngine)
        engine._session = None
        before = {"a.txt": {"size": 100}, "b.txt": {"size": 200}}
        after = {"a.txt": {"size": 150}, "c.txt": {"size": 300}}
        diff = engine._diff_dicts("filesystem", before, after)
        assert "c.txt" in diff.added
        assert "b.txt" in diff.removed
        assert "a.txt" in diff.modified

    def test_state_manager_methods(self):
        from core.worlds.state import WorldStateManager
        for m in ["record_mutation", "get_current_state", "get_state_history",
                   "get_mutation_summary", "get_all_changes"]:
            assert hasattr(WorldStateManager, m)

    def test_snapshot_manager_methods(self):
        from core.worlds.state import WorldSnapshotManager
        for m in ["create_snapshot", "restore_snapshot",
                   "create_base_snapshot", "get_base_snapshot"]:
            assert hasattr(WorldSnapshotManager, m)


# =====================================================================
# C7.7 — Isolation & Network
# =====================================================================


class TestC7Isolation:
    def test_six_isolation_boundaries(self):
        from core.worlds.isolation.isolation import IsolationBoundary
        assert len(list(IsolationBoundary)) == 6

    def test_cross_world_denied(self):
        from core.worlds.isolation import WorldIsolationManager
        iso = WorldIsolationManager.__new__(WorldIsolationManager)
        iso._session = None
        d = iso.check_cross_world_access("wi_1", "wi_2")
        assert not d.allowed

    def test_path_traversal_blocked(self):
        from core.worlds.isolation import WorldIsolationManager
        iso = WorldIsolationManager.__new__(WorldIsolationManager)
        iso._session = None
        d = iso.check_filesystem_isolation(
            "/workspace/../../../etc/passwd", "/data/org/exe", "wi",
        )
        assert not d.allowed

    def test_network_offline(self):
        from core.worlds.isolation import WorldNetworkPolicyManager
        from core.worlds.isolation.network import NetworkRequest
        net = WorldNetworkPolicyManager()
        policy = WorldNetworkPolicy(mode=NetworkMode.OFFLINE)
        d = net.evaluate_request(
            NetworkRequest(url="https://example.com"), policy,
        )
        assert not d.allowed

    def test_credential_isolation(self):
        from core.worlds.isolation import WorldCredentialBroker
        broker = WorldCredentialBroker()
        broker.register_credential(
            organization_id="org", world_instance_id="wi",
            provider="github", scope="read", secret="ghp_xxx",
        )
        ref = broker.get_reference("org", "wi", "github", "read")
        assert "ghp_" not in ref.ref
        injection = broker.inject("org", "wi", "credential://github/read")
        assert injection.secret_value == "ghp_xxx"


# =====================================================================
# C7.8 — SDK & API
# =====================================================================


class TestC7SDK:
    def test_world_sdk_protocol(self):
        from sdk.agent.interfaces.world import WorldSDK
        for m in ["current", "observe", "state", "resources"]:
            assert hasattr(WorldSDK, m)

    def test_sdk_in_dsrt_agent_sdk(self):
        from sdk.agent.sdk import DSRTAgentSDK
        import dataclasses
        assert "world" in {f.name for f in dataclasses.fields(DSRTAgentSDK)}

    def test_world_api_routes(self):
        from core.api.routers.worlds import router
        routes = [r.path for r in router.routes]
        assert len(routes) >= 10


# =====================================================================
# C7.9 — C5/C6 Integration
# =====================================================================


class TestC7Integration:
    def test_world_resolver(self):
        from core.worlds.integration import WorldResolver
        r = WorldResolver.__new__(WorldResolver)
        r._session = None
        r._world_repo = None
        r._world_registry = None
        r._world_manager = None
        assert hasattr(r, "select_world")
        assert hasattr(r, "provision_world")

    def test_verification_hook_is_base_check(self):
        from core.verification.checks.base import BaseCheck
        from core.worlds.integration import WorldVerificationHook
        h = WorldVerificationHook()
        assert isinstance(h, BaseCheck)
        assert h.check_type == "WORLD_STATE_VERIFIED"

    def test_nested_value_with_dots_in_keys(self):
        from core.worlds.integration.verification_hook import WorldVerificationHook
        data = {"filesystem": {"output": {"report.md": "exists"}}}
        val = WorldVerificationHook._get_nested_value(data, "filesystem.output.report.md")
        assert val == "exists"

    def test_nested_value_missing(self):
        from core.worlds.integration.verification_hook import WorldVerificationHook
        val = WorldVerificationHook._get_nested_value({"a": {}}, "a.b.c")
        assert val is None