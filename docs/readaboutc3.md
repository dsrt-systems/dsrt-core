# DSRT Core — Phase C3 Tool & Environment Fabric v1.0

**Status:** Certified Complete (C3.1 → C3.12)
**Core Version:** `1.0.0`
**Agent Contract Version:** `1.0`
**SDK Version:** `1.0.0`
**Database:** Supabase (35 tables in `dsrt` schema)
**Built-in Tools:** 11 (web.search, web.retrieve, http.request, filesystem.read/write/list/delete/move/stat/promote_to_artifact, python.execute)
**Built-in Environments:** 1 (research_workspace)
**Built-in Worlds:** 1 (research_world)

---

## 1. Phase C3 Objective

Build the universal, permission-controlled Tool & Environment Fabric that allows every DSRT Agent to safely perceive and act on the world through a standardized tool system.

> **Agents request actions. Core authorizes, executes, observes, records, and controls them.**

---

## 2. Complete C3 Sub-Phase Summary

| Sub-Phase | Component | Key Deliverables |
|---|---|---|
| **C3.1** | Tool Contracts & Schemas | `ToolManifest`, `ToolIdentity`, `ToolExecutionRequest/Result`, `ToolObservation`, `DSRTTool` Protocol, `ToolExecutionError`, environment/world schemas, approval schemas, 13 new enums |
| **C3.2** | Database Schema & ORM | 15 new ORM models, Alembic migration `2d1cdd708129`, 35 total tables in `dsrt` schema |
| **C3.3** | Tool Registry & Repository | `ToolRegistry`, `ToolRepository`, capability discovery, version resolution |
| **C3.4** | Tool Permission Engine | `ToolPermissionEngine`, intersection logic (7 layers), `ApprovalEvaluator`, `OrgToolPolicy`/`TaskToolPolicy`/`EnvironmentToolPolicy` |
| **C3.5** | Tool Router | `ToolRouter` with full audit trail, `ResolvedToolRoute`, `ToolRoutingDecision`, rejection tracking |
| **C3.6** | Tool Execution Engine | `ToolExecutionEngine`, lifecycle state machine (12 states), timeout/retry/cancellation, observation pipeline, secret redaction |
| **C3.7** | Built-in Tools + SDK Integration | `WebSearchTool`, `WebRetrieveTool`, `HttpRequestTool`, `ToolSDKImpl` (replaces C1 stub), `build_agent_sdk` updated |
| **C3.8** | Filesystem Runtime | `WorkspaceManager` (path traversal prevention, symlink rejection, scope confinement), 7 filesystem tools |
| **C3.9** | Python Sandbox | `PythonSandbox` (cross-platform subprocess isolation), `PythonExecuteTool`, hardened runner script, env scrubbing |
| **C3.10** | Environment Manager | `EnvironmentManager`, `EnvironmentRegistry`, `WorkspaceEnvironmentRuntime`, lifecycle state machine, snapshot interface |
| **C3.11** | Approval System | `ApprovalService`, `ApprovalRepository`, role-gated decisions, expiry, idempotent decide |
| **C3.12** | World Primitive | `WorldRegistry`, `WorldManager`, `RESEARCH_WORLD_MANIFEST`, built-in registration |

---

## 3. The DSRT Execution Loop After C3

```text
                    DSRT
                     │
          ┌──────────┴──────────┐
          │                     │
        THINK                 ACT
          │                     │
       Model Fabric         Tool Fabric
          │                     │
          └──────────┬──────────┘
                     │
                   Agent
                     │
                 Execution
                     │
                   World


4. Key Invariants Enforced
Agents never import tool implementations directly. All interaction flows through sdk.tools.call().
Permission intersection enforces most-restrictive-wins. Tool ∩ Agent ∩ Org ∩ Task ∩ Environment policies.
Side-effect classification gates authorization. EXTERNAL_ACTION and IRREVERSIBLE require approval.
Workspace isolation prevents path traversal. .., absolute paths, symlinks, null bytes all rejected.
Python sandbox runs in hardened subprocess. -I -S flags, scrubbed env, timeout kill, output caps.
Secret redaction in observation pipeline. API keys, tokens, passwords stripped before agent receives output.
Every tool execution is auditable. ToolExecution + ToolObservation + ToolUsage records persisted to Supabase.
Tool events appear in execution trajectory. TOOL_REQUESTED through TOOL_COMPLETED/FAILED/CANCELLED.
Approval requests are role-gated and expire. Only users with sufficient role can grant; stale requests auto-expire.
Worlds compose environments + tools + policies. Research World v1 provides 11 tools under controlled network/filesystem policy.
5. Built-in Tools
Tool Slug	Category	Risk	Side Effect	Description
web.search	web	LOW	READ	DuckDuckGo web search
web.retrieve	web	LOW	READ	Fetch web page content
http.request	http	LOW	READ	Controlled outbound HTTP
filesystem.read	filesystem	LOW	READ	Read workspace files
filesystem.write	filesystem	MEDIUM	WRITE	Write workspace files
filesystem.list	filesystem	LOW	READ	List workspace directory
filesystem.delete	filesystem	MEDIUM	WRITE	Delete workspace files
filesystem.move	filesystem	MEDIUM	WRITE	Move/rename workspace files
filesystem.stat	filesystem	LOW	READ	File metadata
filesystem.promote_to_artifact	filesystem	MEDIUM	WRITE	Promote file to Artifact
python.execute	python	MEDIUM	WRITE	Sandboxed Python execution
6. Run Instructions
Register built-in tools
Python

from core.tools.builtins.registration import register_builtin_tools
from core.storage.database import db_manager

async with db_manager.session() as session:
    results = await register_builtin_tools(session)
    print(results)
Register built-in worlds
Python

from core.worlds.builtins.registration import register_builtin_worlds
from core.storage.database import db_manager

async with db_manager.session() as session:
    results = await register_builtin_worlds(session)
    print(results)
Agent tool call
Python

result = await sdk.tools.call("web.search", {"query": "quantum computing 2025"})
print(result.status)  # "SUCCESS" or "DENIED" or "FAILED"
print(result.output)  # Structured search results
7. Verification
PowerShell

# Run all C3 tests
pytest tests/unit/test_tool_contracts.py tests/unit/test_tool_registry.py tests/unit/test_permission_intersection.py tests/unit/test_approval_evaluator.py tests/unit/test_tool_permission_engine.py tests/unit/test_tool_router.py tests/unit/test_tool_execution_engine.py tests/unit/test_builtin_tools.py tests/unit/test_workspace_manager.py tests/unit/test_filesystem_tools.py tests/unit/test_python_sandbox.py tests/unit/test_python_execute_tool.py tests/unit/test_environment_lifecycle.py tests/unit/test_environment_manager.py tests/unit/test_approval_system.py tests/unit/test_world_primitive.py -v

# Run certification script
python scripts/verify_c3.py
text


