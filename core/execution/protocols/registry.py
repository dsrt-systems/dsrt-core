"""Execution protocol registry mapping protocol enums to concrete handlers."""

from typing import Dict, Type
from sqlalchemy.ext.asyncio import AsyncSession

from core.execution.protocols.base import BaseExecutionProtocol
from core.execution.protocols.direct import DirectExecutionProtocol
from schemas.domain.enums import ErrorCode, ExecutionProtocol


class ProtocolRegistry:
    """Registry mapping ExecutionProtocol enum to protocol implementation classes."""

    _registry: Dict[ExecutionProtocol, Type[BaseExecutionProtocol]] = {}

    @classmethod
    def register(
        cls, protocol: ExecutionProtocol, handler_cls: Type[BaseExecutionProtocol]
    ) -> None:
        cls._registry[protocol] = handler_cls

    @classmethod
    def get_handler(
        cls, protocol: ExecutionProtocol, session: AsyncSession
    ) -> BaseExecutionProtocol:
        handler_cls = cls._registry.get(protocol)
        if not handler_cls:
            raise ValueError(
                f"Unsupported protocol: {protocol.value}. Error code: {ErrorCode.C10_UNSUPPORTED_PROTOCOL.value}"
            )
        return handler_cls(session)


# Register Direct protocol
ProtocolRegistry.register(ExecutionProtocol.DIRECT, DirectExecutionProtocol)