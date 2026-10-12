"""
ExecutionKernel — Central Nervous System of DSRT (C1 §7, §28-29, §31, §33-35).
"""

from __future__ import annotations

from core.agents.registry import AgentRegistry
from core.api.errors.exceptions import NotFoundError
from core.config import get_settings
from core.events.bus import event_bus
from core.kernel.cancellation import cancellation_manager
from core.kernel.fingerprint import configuration_fingerprint, payload_hash
from core.kernel.lifecycle import (
    validate_execution_transition,
    validate_task_transition,
)
from core.kernel.resources import ResourceController
from core.observability.logging import get_logger
from core.repositories import EventRepository, ExecutionRepository, TaskRepository
from core.security.context import SecurityContext
from core.security.permissions import Action, PermissionCheck, get_permission_engine
from core.version import AGENT_CONTRACT_VERSION, CORE_VERSION
from schemas.domain import (
    EventType,
    Execution,
    ExecutionEvent,
    ExecutionStatus,
    ResourceLimits,
    Task,
    TaskCreate,
    TaskStatus,
)


logger = get_logger("dsrt.kernel")


class ExecutionKernel:
    """The DSRT Execution Kernel."""

    def __init__(
        self,
        task_repo: TaskRepository,
        execution_repo: ExecutionRepository,
        agent_registry: AgentRegistry,
        event_repo: EventRepository | None = None,
    ) -> None:
        self._tasks = task_repo
        self._executions = execution_repo
        self._agents = agent_registry
        self._events = event_repo
        self._permissions = get_permission_engine()
        self._settings = get_settings()

    async def emit_event(
        self,
        execution_id: str,
        event_type: str | EventType,
        source: str,
        payload: dict | None = None,
        request_id: str | None = None,
    ) -> ExecutionEvent | None:
        if not self._events:
            return None

        event_type_str = (
            event_type.value if isinstance(event_type, EventType) else event_type
        )

        event_orm = await self._events.append_event(
            execution_id=execution_id,
            event_type=event_type_str,
            source=source,
            payload=payload or {},
            request_id=request_id,
        )

        event_schema = ExecutionEvent.model_validate(event_orm, from_attributes=True)
        await event_bus.publish(event_schema)
        return event_schema

    async def create_task(self, context: SecurityContext, data: TaskCreate) -> Task:
        org_id = context.active_organization_id
        if not org_id:
            raise NotFoundError("Active organization context is required.")

        self._permissions.evaluate(
            context,
            PermissionCheck(action=Action.CREATE_TASK, organization_id=org_id),
        )

        agent_ver = await self._agents.resolve_agent_version(data.agent_slug)

        task_orm = await self._tasks.create(
            organization_id=org_id,
            user_id=context.user_id,
            agent_slug=data.agent_slug,
            objective=data.objective,
            model_identifier=data.model_identifier,
            input_payload=data.input_payload,
            constraints=data.constraints.model_dump(),
        )
        return Task.model_validate(task_orm, from_attributes=True)

    async def create_execution(
        self, context: SecurityContext, task_id: str,
    ) -> Execution:
        task_orm = await self._tasks.get_by_id(task_id)
        if not task_orm:
            raise NotFoundError(f"Task '{task_id}' not found.")

        self._permissions.evaluate(
            context,
            PermissionCheck(action=Action.CREATE_TASK, organization_id=task_orm.organization_id),
        )

        agent_ver = await self._agents.resolve_agent_version(task_orm.agent_slug)
        resource_limits = self._build_resource_limits(task_orm.constraints)
        input_hash = payload_hash(task_orm.input_payload)

        config_hash = configuration_fingerprint(
            core_version=CORE_VERSION,
            agent_version_id=agent_ver.id,
            contract_version=AGENT_CONTRACT_VERSION,
            model_id=None,
            resource_limits=resource_limits.model_dump(),
            task_input_hash=input_hash,
        )

        attempt = len(task_orm.executions) + 1
        execution_orm = await self._executions.create(
            task_id=task_orm.id,
            organization_id=task_orm.organization_id,
            core_version=CORE_VERSION,
            agent_version_id=agent_ver.id,
            contract_version=AGENT_CONTRACT_VERSION,
            configuration_hash=config_hash,
            attempt=attempt,
            resource_limits=resource_limits.model_dump(),
        )

        validate_task_transition(TaskStatus(task_orm.status), TaskStatus.QUEUED)
        await self._tasks.update_status(task_orm, TaskStatus.QUEUED.value)

        await self.emit_event(
            execution_id=execution_orm.id,
            event_type=EventType.EXECUTION_CREATED,
            source="dsrt.kernel",
            payload={
                "task_id": task_orm.id,
                "attempt": attempt,
                "configuration_hash": config_hash,
            },
        )

        # Register cancellation token for this execution
        cancellation_manager.register(execution_orm.id)

        return Execution.model_validate(execution_orm, from_attributes=True)

    async def transition_execution_status(
        self,
        execution_id: str,
        target_status: ExecutionStatus,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        error_metadata: dict | None = None,
        result_summary: dict | None = None,
    ) -> Execution:
        exe_orm = await self._executions.get_by_id(execution_id)
        if not exe_orm:
            raise NotFoundError(f"Execution '{execution_id}' not found.")

        current = ExecutionStatus(exe_orm.status)
        validate_execution_transition(current, target_status)

        await self._executions.update_status(
            exe_orm,
            target_status.value,
            error_code=error_code,
            error_message=error_message,
            error_metadata=error_metadata,
            result_summary=result_summary,
        )

        task_orm = await self._tasks.get_by_id(exe_orm.task_id)
        if task_orm:
            if target_status == ExecutionStatus.RUNNING:
                await self._tasks.update_status(task_orm, TaskStatus.EXECUTING.value)
            elif target_status == ExecutionStatus.COMPLETED:
                await self._tasks.update_status(task_orm, TaskStatus.COMPLETED.value)
            elif target_status == ExecutionStatus.FAILED:
                await self._tasks.update_status(task_orm, TaskStatus.FAILED.value)
            elif target_status == ExecutionStatus.CANCELLED:
                await self._tasks.update_status(task_orm, TaskStatus.CANCELLED.value)

        event_type_map = {
            ExecutionStatus.RUNNING: EventType.EXECUTION_STARTED,
            ExecutionStatus.COMPLETED: EventType.EXECUTION_COMPLETED,
            ExecutionStatus.FAILED: EventType.EXECUTION_FAILED,
            ExecutionStatus.CANCELLING: EventType.EXECUTION_CANCELLING,
            ExecutionStatus.CANCELLED: EventType.EXECUTION_CANCELLED,
        }
        if target_status in event_type_map:
            await self.emit_event(
                execution_id=execution_id,
                event_type=event_type_map[target_status],
                source="dsrt.kernel",
                payload={
                    "previous_status": current.value,
                    "new_status": target_status.value,
                    "error_code": error_code,
                },
            )

        # Cleanup cancellation token if reaching a terminal state
        if target_status in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED):
            cancellation_manager.unregister(execution_id)

        return Execution.model_validate(exe_orm, from_attributes=True)

    async def cancel_execution(
        self, context: SecurityContext, execution_id: str,
    ) -> Execution:
        """Cancel an execution (C1 §34)."""
        exe_orm = await self._executions.get_by_id(execution_id)
        if not exe_orm:
            raise NotFoundError(f"Execution '{execution_id}' not found.")

        self._permissions.evaluate(
            context,
            PermissionCheck(
                action=Action.CANCEL_EXECUTION,
                organization_id=exe_orm.organization_id,
            ),
        )

        current = ExecutionStatus(exe_orm.status)
        if current in (
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
        ):
            return Execution.model_validate(exe_orm, from_attributes=True)

        # 1. Transition state to CANCELLING
        exe = await self.transition_execution_status(
            execution_id, ExecutionStatus.CANCELLING,
        )

        # 2. Broadcast cancellation signal to the running agent loop
        cancellation_manager.cancel(execution_id)

        # 3. Transition to CANCELLED
        return await self.transition_execution_status(
            execution_id,
            ExecutionStatus.CANCELLED,
            error_code="EXECUTION_CANCELLED",
            error_message="Execution cancelled by user request.",
        )

    def create_resource_controller(self, execution: Execution) -> ResourceController:
        """Create a transient ResourceController bound to this execution."""
        return ResourceController(execution.id, execution.resource_limits)

    def _build_resource_limits(self, task_constraints: dict) -> ResourceLimits:
        max_duration = task_constraints.get("max_duration_seconds")
        if max_duration is None:
            max_duration = self._settings.default_execution_timeout_seconds

        max_models = task_constraints.get("max_model_calls")
        if max_models is None:
            max_models = self._settings.default_max_model_calls

        max_tools = task_constraints.get("max_tool_calls")
        if max_tools is None:
            max_tools = self._settings.default_max_tool_calls

        max_storage = task_constraints.get("max_storage_mb")
        if max_storage is None:
            max_storage = self._settings.default_max_storage_mb

        max_tokens = task_constraints.get("max_tokens")

        return ResourceLimits(
            max_duration_seconds=max_duration,
            max_model_calls=max_models,
            max_tool_calls=max_tools,
            max_storage_mb=max_storage,
            max_tokens=max_tokens,
        )