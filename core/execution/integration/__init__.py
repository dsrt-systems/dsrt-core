# Path: core/execution/integration/__init__.py
"""
C10.10 — System Integration.

Binds controller, protocols, evaluation, economics, observability and
comparison behind stable runtime contracts.
"""

from core.execution.integration.contracts import (
    ExecutionRequest,
    ExecutionResult,
    ValidationResult,
    PreparedExecution,
    ProtocolExecutionResult,
)
from core.execution.integration.protocol_base import ExecutionProtocol
from core.execution.integration.dependencies import (
    RuntimeDependencies,
    NullRuntimeDependencies,
)
from core.execution.integration.unified_engine import UnifiedExecutionEngine

__all__ = [
    "ExecutionRequest",
    "ExecutionResult",
    "ValidationResult",
    "PreparedExecution",
    "ProtocolExecutionResult",
    "ExecutionProtocol",
    "RuntimeDependencies",
    "NullRuntimeDependencies",
    "UnifiedExecutionEngine",
]