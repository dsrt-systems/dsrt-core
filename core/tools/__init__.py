"""
DSRT Tool Fabric — Core Package.

The DSRTTool Protocol defined here is the contract every concrete tool
implementation (web.search, http.request, python.execute, filesystem.read, ...)
must satisfy. Tool implementations live under `core/tools/builtins/` or are
provided by extensions.

Agents NEVER import this module. Agents only ever interact with tools through
`sdk.agent.interfaces.tools.ToolSDK` which is injected via the DSRTAgentSDK.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from schemas.domain.tool import (
    ToolContext,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolHealth,
    ToolIdentity,
    ToolInitializationResult,
    ToolManifest,
)


@runtime_checkable
class DSRTTool(Protocol):
    """
    Contract every DSRT tool implementation must satisfy (C3 §5).

    Lifecycle:
        1. Tool is registered with the ToolRegistry (via its manifest).
        2. The ToolExecutionEngine instantiates the implementation class.
        3. initialize(context) is called ONCE per execution context.
        4. execute(request) may be called many times, concurrently if the
           manifest permits.
        5. cancel(request_id) may be called at any time while execute() is
           running — the implementation must cooperatively stop.
        6. health() is polled by the ToolHealthMonitor.

    Implementations MUST:
      - Be stateless w.r.t. previous executions once execute() returns.
      - Honour the timeout given in ToolExecutionRequest.timeout_seconds.
      - Never log, return, or expose credential material in observations
        or results.
      - Attach provenance to every observation.
      - Raise only `ToolRuntimeError` (or a subclass) from execute();
        all other exceptions are coerced to TOOL_RUNTIME_FAILURE by the
        Execution Engine.
    """

    identity: ToolIdentity
    manifest: ToolManifest

    async def initialize(
        self,
        context: ToolContext,
    ) -> ToolInitializationResult:
        """Prepare the tool for execution within the given context."""
        ...

    async def execute(
        self,
        request: ToolExecutionRequest,
    ) -> ToolExecutionResult:
        """Execute the tool and return a normalized result."""
        ...

    async def cancel(
        self,
        request_id: str,
    ) -> None:
        """Cooperatively cancel an in-flight execution."""
        ...

    async def health(self) -> ToolHealth:
        """Report current operational health."""
        ...


__all__ = ["DSRTTool"]