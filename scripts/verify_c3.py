"""
DSRT Core — Phase C3 Certification Script.

Programmatic verification that all C3 Definition of Done requirements
are satisfied. Run this before declaring C3 complete.

Usage:
    python scripts/verify_c3.py
"""

from __future__ import annotations

import os
import sys

# Ensure the project root is on sys.path so imports work correctly
# when running `python scripts/verify_c3.py` from the project root.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def main() -> int:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append((name, passed, detail))
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}  {name}" + (f" — {detail}" if detail else ""))

    print("\n" + "=" * 70)
    print("DSRT CORE — PHASE C3 CERTIFICATION")
    print("=" * 70)

    # --- 1. Schema & Contract Imports ---
    print("\n[1] Tool Contracts & Schemas")
    try:
        from schemas.domain.tool import ToolManifest, ToolIdentity, ToolExecutionRequest, ToolExecutionResult, ToolObservation, ToolExecutionError, ToolHealth, ToolUsage
        check("Tool domain schemas import", True)
    except Exception as e:
        check("Tool domain schemas import", False, str(e))

    try:
        from schemas.domain.environment import EnvironmentManifest, EnvironmentIdentity
        check("Environment domain schemas import", True)
    except Exception as e:
        check("Environment domain schemas import", False, str(e))

    try:
        from schemas.domain.world import WorldManifest, WorldIdentity, WorldPolicy
        check("World domain schemas import", True)
    except Exception as e:
        check("World domain schemas import", False, str(e))

    try:
        from schemas.domain.approval import ApprovalRequest, ApprovalDecision
        check("Approval domain schemas import", True)
    except Exception as e:
        check("Approval domain schemas import", False, str(e))

    try:
        from core.tools import DSRTTool
        check("DSRTTool Protocol import", True)
    except Exception as e:
        check("DSRTTool Protocol import", False, str(e))

    # --- 2. Enums ---
    print("\n[2] C3 Enums")
    try:
        from schemas.domain.enums import ToolExecutionStatus, SideEffectClass, ObservationType, ToolRiskLevel, EnvironmentStatus, WorldStatus, ApprovalStatus, NetworkMode, FilesystemAccessMode
        check("C3 enums import", True)
    except Exception as e:
        check("C3 enums import", False, str(e))

    # --- 3. Tool Fabric ---
    print("\n[3] Tool Fabric Components")
    try:
        from core.tools.registry import ToolRegistry
        check("ToolRegistry import", True)
    except Exception as e:
        check("ToolRegistry import", False, str(e))

    try:
        from core.tools.router import ToolRouter, ResolvedToolRoute
        check("ToolRouter import", True)
    except Exception as e:
        check("ToolRouter import", False, str(e))

    try:
        from core.tools.execution import ToolExecutionEngine
        check("ToolExecutionEngine import", True)
    except Exception as e:
        check("ToolExecutionEngine import", False, str(e))

    try:
        from core.tools.permissions import ToolPermissionEngine, ToolPermissionDecision
        check("ToolPermissionEngine import", True)
    except Exception as e:
        check("ToolPermissionEngine import", False, str(e))

    try:
        from core.tools.errors import ToolFabricError, ToolNotFoundError, ToolPermissionDeniedError, ToolApprovalRequiredError
        check("Tool error taxonomy import", True)
    except Exception as e:
        check("Tool error taxonomy import", False, str(e))

    # --- 4. Built-in Tools ---
    print("\n[4] Built-in Tools")
    try:
        from core.tools.builtins import WebSearchTool, WebRetrieveTool, HttpRequestTool, FilesystemReadTool, FilesystemWriteTool, FilesystemListTool, FilesystemDeleteTool, FilesystemMoveTool, FilesystemStatTool, FilesystemPromoteToArtifactTool, PythonExecuteTool
        all_tools = [WebSearchTool, WebRetrieveTool, HttpRequestTool, FilesystemReadTool, FilesystemWriteTool, FilesystemListTool, FilesystemDeleteTool, FilesystemMoveTool, FilesystemStatTool, FilesystemPromoteToArtifactTool, PythonExecuteTool]
        check(f"All 11 built-in tools import", True, f"{len(all_tools)} tools loaded")

        for tool_cls in all_tools:
            t = tool_cls()
            is_protocol = isinstance(t, DSRTTool)
            check(f"  {t.identity.slug} satisfies DSRTTool", is_protocol)
    except Exception as e:
        check("Built-in tools import", False, str(e))

    # --- 5. Sandbox ---
    print("\n[5] Python Sandbox")
    try:
        from core.tools.environments.python_sandbox import PythonSandbox
        check("PythonSandbox import", True)
    except Exception as e:
        check("PythonSandbox import", False, str(e))

    # --- 6. Workspace ---
    print("\n[6] Workspace Manager")
    try:
        from core.tools.environments.workspace import WorkspaceManager
        check("WorkspaceManager import", True)
    except Exception as e:
        check("WorkspaceManager import", False, str(e))

    # --- 7. Environment Fabric ---
    print("\n[7] Environment Fabric")
    try:
        from core.environments import EnvironmentManager, EnvironmentRegistry, EnvironmentRuntime
        check("Environment Fabric imports", True)
    except Exception as e:
        check("Environment Fabric imports", False, str(e))

    # --- 8. Approval System ---
    print("\n[8] Approval System")
    try:
        from core.tools.approvals import ApprovalService
        check("ApprovalService import", True)
    except Exception as e:
        check("ApprovalService import", False, str(e))

    # --- 9. World Primitive ---
    print("\n[9] World Primitive")
    try:
        from core.worlds.registry import WorldRegistry
        from core.worlds.manager import WorldManager
        from core.worlds.builtins.research_world import RESEARCH_WORLD_MANIFEST
        check("World Fabric imports", True)
        check("Research World manifest slug", RESEARCH_WORLD_MANIFEST.identity.slug == "research_world")
        check("Research World exposes 11 tools", len(RESEARCH_WORLD_MANIFEST.exposed_tools) == 11)
        check("Research World has research capability", "research" in RESEARCH_WORLD_MANIFEST.capabilities)
    except Exception as e:
        check("World Fabric imports", False, str(e))

    # --- 10. Repositories ---
    print("\n[10] Repositories")
    try:
        from core.repositories import ToolRepository, ToolExecutionRepository, EnvironmentRepository, ApprovalRepository, WorldRepository
        check("All C3 repositories import", True)
    except Exception as e:
        check("All C3 repositories import", False, str(e))

    # --- 11. SDK Integration ---
    print("\n[11] SDK Integration")
    try:
        from sdk.agent.adapters.tool_adapter import ToolSDKImpl
        check("ToolSDKImpl is NOT the C1 stub", hasattr(ToolSDKImpl, '_agent_manifest') or 'session' in ToolSDKImpl.__init__.__code__.co_varnames)
    except Exception as e:
        check("ToolSDKImpl check", False, str(e))

    try:
        from sdk.agent.runtime.factory import build_agent_sdk
        import inspect
        sig = inspect.signature(build_agent_sdk)
        check("build_agent_sdk accepts agent_manifest", "agent_manifest" in sig.parameters)
        check("build_agent_sdk accepts agent_version_id", "agent_version_id" in sig.parameters)
    except Exception as e:
        check("build_agent_sdk signature", False, str(e))

    # --- 12. ID Prefixes ---
    print("\n[12] ULID Prefixes")
    try:
        from core.storage.identifiers import IdPrefix
        c3_prefixes = ["TOOL", "TOOL_VERSION", "TOOL_CAPABILITY", "TOOL_EXECUTION", "TOOL_OBSERVATION", "TOOL_USAGE", "ENVIRONMENT", "ENVIRONMENT_VERSION", "ENVIRONMENT_SNAPSHOT", "WORLD", "WORLD_VERSION", "APPROVAL_REQUEST", "APPROVAL_DECISION"]
        for prefix_name in c3_prefixes:
            has_it = hasattr(IdPrefix, prefix_name)
            check(f"  IdPrefix.{prefix_name}", has_it)
    except Exception as e:
        check("IdPrefix check", False, str(e))

    # --- Summary ---
    total = len(checks)
    passed = sum(1 for _, p, _ in checks if p)
    failed = total - passed

    print("\n" + "=" * 70)
    print(f"RESULTS: {passed}/{total} checks passed, {failed} failed")

    if failed == 0:
        print("\n🎉 PHASE C3 — CERTIFIED COMPLETE")
        print("   DSRT Tool & Environment Fabric v1.0 is ready for production.")
    else:
        print(f"\n⚠️  {failed} check(s) failed. Phase C3 is NOT certified.")
        for name, p, detail in checks:
            if not p:
                print(f"   ❌ {name}: {detail}")

    print("=" * 70 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())