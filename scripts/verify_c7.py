"""
C7 Phase Certification Script.
Run: python scripts/verify_c7.py
"""

from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def verify_c7() -> bool:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        checks.append((name, condition, detail))

    # C7.1
    try:
        from schemas.domain.enums import (
            WorldComponentType, WorldClockMode, WorldChangeType,
            WorldActionReversibility, WorldSnapshotType, EventType,
        )
        from schemas.domain.world import (
            WorldManifest, WorldResourceLimits, WorldComponentSpec,
            WorldProvisionRequest, WorldStateDiff, WorldChange,
            WorldNetworkPolicy, WorldCredentialRef, WorldTemplate,
        )
        assert len(list(WorldComponentType)) == 11
        check("C7.1 Schemas and Enums", True)
    except Exception as e:
        check("C7.1 Schemas and Enums", False, str(e))

    # C7.2
    try:
        from core.storage.models import (
            WorldComponentORM, WorldSnapshotORM,
            WorldStateVersionORM, WorldStateChangeORM,
            WorldNetworkPolicyORM, WorldHealthRecordORM,
        )
        from core.storage.models.world import WorldInstanceORM
        assert hasattr(WorldInstanceORM, "resource_profile")
        check("C7.2 Database Models", True)
    except Exception as e:
        check("C7.2 Database Models", False, str(e))

    # C7.3
    try:
        from core.worlds.templates import (
            SOFTWARE_WORLD_MANIFEST, DATA_SCIENCE_WORLD_MANIFEST,
            RESEARCH_WORLD_V2_MANIFEST,
        )
        assert SOFTWARE_WORLD_MANIFEST.identity.slug == "software_engineering_world"
        check("C7.3 Templates and Registry", True)
    except Exception as e:
        check("C7.3 Templates and Registry", False, str(e))

    # C7.4
    try:
        from core.worlds.runtime.lifecycle import WorldLifecycleManager
        from core.worlds.runtime.runtime import DSRTWorld, WorldRuntime
        from core.worlds.manager.manager import WorldManager
        lm = WorldLifecycleManager()
        lm.validate_transition("RUNNING", "PAUSING")
        check("C7.4 Runtime and Lifecycle", True)
    except Exception as e:
        check("C7.4 Runtime and Lifecycle", False, str(e))

    # C7.5
    try:
        from core.worlds.components import (
            FilesystemComponent, BrowserComponent, TerminalComponent,
            RuntimeComponent, DatabaseComponent, ComponentManager,
        )
        check("C7.5 Components", True)
    except Exception as e:
        check("C7.5 Components", False, str(e))

    # C7.6
    try:
        from core.worlds.state import (
            WorldStateManager, WorldSnapshotManager, WorldDiffEngine,
        )
        check("C7.6 State and Snapshots", True)
    except Exception as e:
        check("C7.6 State and Snapshots", False, str(e))

    # C7.7
    try:
        from core.worlds.isolation import (
            WorldIsolationManager, WorldNetworkPolicyManager,
            WorldCredentialBroker,
        )
        check("C7.7 Isolation and Network", True)
    except Exception as e:
        check("C7.7 Isolation and Network", False, str(e))

    # C7.8
    try:
        from sdk.agent.interfaces.world import WorldSDK
        from sdk.agent.adapters.world_adapter import WorldSDKImpl
        from core.api.routers.worlds import router
        assert len(router.routes) >= 10
        check("C7.8 SDK and API", True)
    except Exception as e:
        check("C7.8 SDK and API", False, str(e))

    # C7.9
    try:
        from core.worlds.integration import WorldResolver, WorldVerificationHook
        from core.verification.checks.base import BaseCheck
        h = WorldVerificationHook()
        assert isinstance(h, BaseCheck)
        check("C7.9 C5/C6 Integration", True)
    except Exception as e:
        check("C7.9 C5/C6 Integration", False, str(e))

    # Summary
    print("\n" + "=" * 60)
    print("DSRT CORE - PHASE C7 CERTIFICATION")
    print("=" * 60)

    passed = sum(1 for _, ok, _ in checks if ok)
    failed = sum(1 for _, ok, _ in checks if not ok)

    for name, ok, detail in checks:
        icon = "[+]" if ok else "[!]"
        status = "PASS" if ok else "FAIL"
        line = f"  {icon} {status}  {name}"
        if detail:
            line += f" -- {detail}"
        print(line)

    print(f"\n  Total: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed > 0:
        print("\n  C7 CERTIFICATION FAILED")
        return False
    else:
        print("\n  C7 PHASE CERTIFIED COMPLETE")
        return True


if __name__ == "__main__":
    success = verify_c7()
    sys.exit(0 if success else 1)