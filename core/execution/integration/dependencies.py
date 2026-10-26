# Path: core/execution/integration/dependencies.py
"""
Injected runtime dependency interfaces for C1–C9 capabilities.

C10 must not import concrete provider/DB internals into protocols.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class AgentRegistryPort(Protocol):
    async def resolve(self, agent_selection: Dict[str, Any]) -> Dict[str, Any]:
        ...


@runtime_checkable
class ModelGatewayPort(Protocol):
    async def generate(self, connection: Dict[str, Any], prompt: str, **kwargs: Any) -> Dict[str, Any]:
        ...


@runtime_checkable
class ContextEnginePort(Protocol):
    async def compile(self, workspace_id: str, task_id: str, **kwargs: Any) -> Dict[str, Any]:
        ...


@runtime_checkable
class OrchestratorPort(Protocol):
    async def plan(self, task: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        ...


@runtime_checkable
class ToolRuntimePort(Protocol):
    async def invoke(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        ...


@runtime_checkable
class WorldRuntimePort(Protocol):
    async def provision(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        ...


@runtime_checkable
class VerificationPort(Protocol):
    async def verify(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ...


@runtime_checkable
class BenchmarkRegistryPort(Protocol):
    async def resolve_suite(self, suite_id: str) -> Dict[str, Any]:
        ...


@runtime_checkable
class EventSDKPort(Protocol):
    async def publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        ...


@runtime_checkable
class ArtifactSDKPort(Protocol):
    async def store(self, workspace_id: str, name: str, content: bytes, **kwargs: Any) -> str:
        ...


@runtime_checkable
class StateSDKPort(Protocol):
    async def save_execution_state(self, execution_id: str, state: Dict[str, Any]) -> None:
        ...

    async def load_execution_state(self, execution_id: str) -> Optional[Dict[str, Any]]:
        ...


class _NullAsync:
    """Minimal async null object for optional ports."""

    def __init__(self, default: Any = None):
        self._default = default

    async def resolve(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {}

    async def generate(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"output": None, "usage": {}}

    async def compile(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {}

    async def plan(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"steps": []}

    async def invoke(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"ok": False, "error": "tool_runtime_not_configured"}

    async def provision(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {}

    async def verify(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"passed": True, "checks": []}

    async def resolve_suite(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {}

    async def publish(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def store(self, *args: Any, **kwargs: Any) -> str:
        return ""

    async def save_execution_state(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def load_execution_state(self, *args: Any, **kwargs: Any) -> Optional[Dict[str, Any]]:
        return None


@dataclass
class RuntimeDependencies:
    """Bundle of injected ports used by the unified engine."""

    agents: Any = field(default_factory=_NullAsync)
    models: Any = field(default_factory=_NullAsync)
    context: Any = field(default_factory=_NullAsync)
    orchestrator: Any = field(default_factory=_NullAsync)
    tools: Any = field(default_factory=_NullAsync)
    world: Any = field(default_factory=_NullAsync)
    verification: Any = field(default_factory=_NullAsync)
    benchmarks: Any = field(default_factory=_NullAsync)
    events: Any = field(default_factory=_NullAsync)
    artifacts: Any = field(default_factory=_NullAsync)
    state: Any = field(default_factory=_NullAsync)


def NullRuntimeDependencies() -> RuntimeDependencies:
    return RuntimeDependencies()