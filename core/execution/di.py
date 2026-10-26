"""Dependency injection wiring container for C10 execution components."""

from sqlalchemy.ext.asyncio import AsyncSession

from core.execution.controller.admission import ExecutionAdmissionGate
from core.execution.controller.controller import ExecutionController
from core.execution.controller.lifecycle import ExecutionLifecycleManager
from core.execution.controller.recovery import ExecutionStartupScanner
from core.execution.repositories.configuration_repository import ExecutionConfigurationRepository
from core.execution.repositories.idempotency_repository import IdempotencyRepository
from core.execution.repositories.step_repository import ExecutionStepRepository
from core.execution.repositories.trace_repository import ExecutionTraceRepository


class ExecutionContainer:
    """Factory container producing C10 execution controller and repositories for a session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.trace_repo = ExecutionTraceRepository(session)
        self.step_repo = ExecutionStepRepository(session)
        self.config_repo = ExecutionConfigurationRepository(session)
        self.idempotency_repo = IdempotencyRepository(session)
        self.admission_gate = ExecutionAdmissionGate(session)
        self.lifecycle_manager = ExecutionLifecycleManager(session)
        self.startup_scanner = ExecutionStartupScanner(session)
        self.controller = ExecutionController(session)