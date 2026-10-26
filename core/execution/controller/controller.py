"""Master Execution Controller governing execution admission, lifecycle, and protocols."""

import hashlib
import json
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from core.execution.controller.admission import ExecutionAdmissionGate
from core.execution.controller.cancellation import ExecutionCancellationRegistry
from core.execution.controller.lifecycle import ExecutionLifecycleManager
from core.execution.protocols.registry import ProtocolRegistry
from core.execution.repositories.configuration_repository import ExecutionConfigurationRepository
from core.execution.repositories.idempotency_repository import IdempotencyRepository
from core.execution.repositories.trace_repository import ExecutionTraceRepository
from schemas.domain.enums import ErrorCode
from schemas.domain.execution_c10 import (
    ExecutionConfigurationCreate,
    ExecutionTrace,
    ExecutionTraceCreate,
)


class ExecutionController:
    """Core controller managing admission, state persistence, idempotency, and protocol dispatch."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.admission_gate = ExecutionAdmissionGate(session)
        self.lifecycle_manager = ExecutionLifecycleManager(session)
        self.config_repo = ExecutionConfigurationRepository(session)
        self.trace_repo = ExecutionTraceRepository(session)
        self.idempotency_repo = IdempotencyRepository(session)
        self.cancellation_registry = ExecutionCancellationRegistry.get_instance()

    async def execute(
        self,
        config_create: ExecutionConfigurationCreate,
        input_payload: Dict[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> ExecutionTrace:
        """Executes a configuration through formal admission, state transitions, and protocol handling."""
        # 1. Idempotency Check
        if idempotency_key:
            key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
            existing = await self.idempotency_repo.get_key(
                config_create.organization_id, key_hash
            )
            if existing and existing.response_payload:
                existing_trace = await self.trace_repo.get_by_id(existing.execution_id)
                if existing_trace:
                    return ExecutionTrace.model_validate(existing_trace, from_attributes=True)

        # 2. Admission Check
        admitted, decision, reason = await self.admission_gate.evaluate_admission(config_create)
        if not admitted:
            config_orm = await self.config_repo.create_configuration(config_create)
            trace_create = ExecutionTraceCreate(
                organization_id=config_create.organization_id,
                protocol=config_create.protocol,
                mode=config_create.mode,
            )
            trace_orm = await self.trace_repo.create_trace(trace_create, config_orm.id)
            await self.lifecycle_manager.transition_to_failed(
                trace_orm.id, error_code=reason, error_message="Admission gate rejected configuration"
            )
            updated = await self.trace_repo.get_by_id(trace_orm.id)
            return ExecutionTrace.model_validate(updated, from_attributes=True)

        # 3. Save Configuration & Create Admitted Trace
        config_orm = await self.config_repo.create_configuration(config_create)
        trace_create = ExecutionTraceCreate(
            organization_id=config_create.organization_id,
            protocol=config_create.protocol,
            mode=config_create.mode,
        )
        trace_orm = await self.trace_repo.create_trace(trace_create, config_orm.id)
        await self.lifecycle_manager.transition_to_admitted(trace_orm.id)

        # 4. Save Idempotency Key record
        if idempotency_key:
            req_hash = hashlib.sha256(
                json.dumps(input_payload, sort_keys=True).encode("utf-8")
            ).hexdigest()
            await self.idempotency_repo.create_key(
                organization_id=config_create.organization_id,
                key_hash=key_hash,
                key_string=idempotency_key,
                execution_id=trace_orm.id,
                request_hash=req_hash,
            )

        # 5. Execute Protocol
        await self.lifecycle_manager.transition_to_running(trace_orm.id)
        try:
            handler = ProtocolRegistry.get_handler(config_create.protocol, self.session)
            result_trace = await handler.execute(trace_orm.id, config_create, input_payload)
            await self.lifecycle_manager.transition_to_completed(trace_orm.id)

            updated = await self.trace_repo.get_by_id(trace_orm.id)
            final_trace = ExecutionTrace.model_validate(updated, from_attributes=True)

            if idempotency_key:
                await self.idempotency_repo.complete_key(
                    key_hash, final_trace.model_dump(mode="json")
                )

            return final_trace

        except Exception as exc:
            await self.lifecycle_manager.transition_to_failed(
                trace_orm.id,
                error_code=ErrorCode.C10_EXECUTION_FAILED.value,
                error_message=str(exc),
            )
            updated = await self.trace_repo.get_by_id(trace_orm.id)
            return ExecutionTrace.model_validate(updated, from_attributes=True)