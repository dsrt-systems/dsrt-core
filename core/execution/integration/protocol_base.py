# Path: core/execution/integration/protocol_base.py
"""
ExecutionProtocol contract — registerable without modifying the controller.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.execution.integration.contracts import (
    ExecutionRequest,
    PreparedExecution,
    ProtocolExecutionResult,
    ValidationResult,
    ExecutionResult,
)


@runtime_checkable
class ExecutionProtocol(Protocol):
    protocol_id: str
    protocol_version: str

    async def validate(self, request: ExecutionRequest) -> ValidationResult:
        ...

    async def prepare(self, request: ExecutionRequest) -> PreparedExecution:
        ...

    async def execute(self, prepared: PreparedExecution) -> ProtocolExecutionResult:
        ...

    async def finalize(self, execution_id: str) -> ExecutionResult:
        ...