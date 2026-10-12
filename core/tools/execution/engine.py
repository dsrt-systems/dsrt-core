"""
Tool Execution Engine (C3 §16-19, §41-47).

The runtime heart of the Tool Fabric. Orchestrates the complete tool
execution lifecycle from REQUESTED through COMPLETED/FAILED/CANCELLED.

Architecture:
    ResolvedToolRoute (from C3.5 Router)
        ↓
    [1] Create ToolExecution record (DB)
    [2] Load tool implementation class
    [3] Initialize tool with context
    [4] Execute with retry + timeout + cancellation
    [5] Normalize output → observations
    [6] Persist observations + usage
    [7] Emit lifecycle events
    [8] Return ToolExecutionResult
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import EventType, ObservationType, ToolExecutionStatus
from schemas.domain.tool import (
    ToolContext,
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolObservation,
    ToolUsage,
)

from core.kernel.cancellation import cancellation_manager
from core.kernel.fingerprint import content_hash
from core.kernel.kernel import ExecutionKernel
from core.observability.logging import get_logger
from core.repositories.tool_execution_repository import ToolExecutionRepository
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models import Artifact
from core.tools import DSRTTool
from core.tools.errors import (
    ToolCancelledError,
    ToolOutputTooLargeError,
    ToolRuntimeError,
    ToolTimeoutError,
)
from core.tools.execution.impl_loader import load_tool_implementation
from core.tools.execution.lifecycle import (
    is_terminal,
    validate_tool_execution_transition,
)
from core.tools.execution.retry import execute_with_retry
from core.tools.observations.normalizer import normalize_output
from core.tools.router.decision import ResolvedToolRoute


logger = get_logger("dsrt.tools.execution")

# Absolute ceiling timeout — no tool can run longer than this
_MAX_CEILING_TIMEOUT_SECONDS = 3600  # 1 hour


class ToolExecutionEngine:
    """Orchestrates the complete tool execution lifecycle."""

    def __init__(
        self,
        session: AsyncSession,
        kernel: ExecutionKernel,
    ) -> None:
        self._session = session
        self._kernel = kernel
        self._repo = ToolExecutionRepository(session)

    async def execute(
        self,
        request: ToolExecutionRequest,
        route: ResolvedToolRoute,
    ) -> ToolExecutionResult:
        """Execute a tool call through the complete lifecycle.

        This is the primary entry point called by ToolSDKImpl.
        """
        start_time = time.perf_counter()
        tool_slug = request.tool_slug
        tool_version = route.tool_version
        manifest = route.tool_manifest

        # ------------------------------------------------------------------
        # 1. Idempotency check
        # ------------------------------------------------------------------
        if request.idempotency_key:
            existing = await self._repo.get_by_request_id(request.idempotency_key)
            if existing and is_terminal(ToolExecutionStatus(existing.status)):
                logger.info(
                    "tool_execution_idempotent_hit",
                    request_id=request.request_id,
                    existing_id=existing.id,
                    status=existing.status,
                )
                return self._orm_to_result(existing)

        # ------------------------------------------------------------------
        # 2. Create ToolExecution record
        # ------------------------------------------------------------------
        tool_exe = await self._repo.create_execution(
            request_id=request.idempotency_key or request.request_id,
            tool_slug=tool_slug,
            tool_version=tool_version,
            execution_id=request.execution_id,
            task_id=request.task_id,
            organization_id=request.organization_id,
            agent_slug=request.agent_slug,
            agent_version=request.agent_version,
            arguments=request.arguments,
            environment_instance_id=request.environment_id,
            attempt=request.attempt,
        )

        await self._transition(tool_exe, ToolExecutionStatus.REQUESTED)
        await self._emit_tool_event(
            request.execution_id, EventType.TOOL_REQUESTED, request.request_id,
            {"tool_slug": tool_slug, "tool_version": tool_version},
        )

        # ------------------------------------------------------------------
        # 3. Transition to AUTHORIZED (permission already enforced by Router)
        # ------------------------------------------------------------------
        await self._transition(tool_exe, ToolExecutionStatus.AUTHORIZED)

        # ------------------------------------------------------------------
        # 4. Load implementation & initialize
        # ------------------------------------------------------------------
        try:
            impl_cls = load_tool_implementation(route.implementation_class)
            tool_instance: DSRTTool = impl_cls()  # type: ignore[assignment]
        except Exception as e:
            return await self._fail_execution(
                tool_exe, request, start_time,
                error_code="TOOL_RUNTIME_FAILURE",
                error_message=f"Failed to load tool implementation: {e}",
            )

        tool_context = ToolContext(
            execution_id=request.execution_id,
            task_id=request.task_id,
            organization_id=request.organization_id,
            agent_slug=request.agent_slug,
            agent_version=request.agent_version,
            environment_id=request.environment_id,
        )

        try:
            init_result = await tool_instance.initialize(tool_context)
            if not init_result.ready:
                return await self._fail_execution(
                    tool_exe, request, start_time,
                    error_code="TOOL_RUNTIME_FAILURE",
                    error_message=f"Tool initialization failed: {init_result.message}",
                )
        except Exception as e:
            return await self._fail_execution(
                tool_exe, request, start_time,
                error_code="TOOL_RUNTIME_FAILURE",
                error_message=f"Tool initialization exception: {e}",
            )

        # ------------------------------------------------------------------
        # 5. Transition to STARTED → RUNNING
        # ------------------------------------------------------------------
        await self._transition(tool_exe, ToolExecutionStatus.STARTED)
        await self._transition(tool_exe, ToolExecutionStatus.RUNNING)
        await self._emit_tool_event(
            request.execution_id, EventType.TOOL_STARTED, request.request_id,
            {"tool_slug": tool_slug},
        )

        # ------------------------------------------------------------------
        # 6. Execute with timeout + retry + cancellation
        # ------------------------------------------------------------------
        timeout = self._resolve_timeout(request, manifest)
        cancel_token = cancellation_manager.get_token(request.execution_id)

        async def _do_execute() -> ToolExecutionResult:
            return await tool_instance.execute(request)

        try:
            # Apply timeout wrapper
            if timeout > 0:
                raw_result = await asyncio.wait_for(
                    execute_with_retry(
                        _do_execute,
                        manifest.retry,
                        cancel_event=cancel_token,
                    ),
                    timeout=timeout,
                )
            else:
                raw_result = await execute_with_retry(
                    _do_execute,
                    manifest.retry,
                    cancel_event=cancel_token,
                )

        except asyncio.TimeoutError:
            return await self._fail_execution(
                tool_exe, request, start_time,
                error_code="TOOL_TIMEOUT",
                error_message=f"Tool '{tool_slug}' timed out after {timeout}s.",
            )
        except asyncio.CancelledError:
            return await self._cancel_execution(tool_exe, request, start_time)
        except ToolCancelledError:
            return await self._cancel_execution(tool_exe, request, start_time)
        except Exception as e:
            return await self._fail_execution(
                tool_exe, request, start_time,
                error_code="TOOL_RUNTIME_FAILURE",
                error_message=str(e),
            )

        # ------------------------------------------------------------------
        # 7. Check cancellation after execution
        # ------------------------------------------------------------------
        if cancel_token and cancel_token.is_set():
            return await self._cancel_execution(tool_exe, request, start_time)

        # ------------------------------------------------------------------
        # 8. Normalize output → observations
        # ------------------------------------------------------------------
        await self._transition(tool_exe, ToolExecutionStatus.OBSERVING)

        observations = normalize_output(
            raw_result.output,
            tool_slug=tool_slug,
            tool_execution_id=tool_exe.id,
            execution_id=request.execution_id,
            max_bytes=manifest.limits.max_output_bytes,
        )

        # Persist observations
        for obs in observations:
            await self._repo.create_observation(
                tool_execution_id=tool_exe.id,
                execution_id=request.execution_id,
                observation_type=obs.observation_type.value,
                content=obs.content,
                summary=obs.summary,
                source=obs.source,
                confidence=obs.confidence,
                truncated=obs.truncated,
                size_bytes=obs.size_bytes,
                artifact_id=obs.artifact_id,
                provenance=obs.provenance,
                metadata=obs.metadata,
            )
            await self._emit_tool_event(
                request.execution_id, EventType.TOOL_OBSERVATION_CREATED,
                request.request_id,
                {"observation_type": obs.observation_type.value, "size_bytes": obs.size_bytes},
            )

        # ------------------------------------------------------------------
        # 9. Persist usage
        # ------------------------------------------------------------------
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        await self._repo.create_usage(
            tool_execution_id=tool_exe.id,
            execution_id=request.execution_id,
            duration_ms=duration_ms,
        )

        # ------------------------------------------------------------------
        # 10. Finalize
        # ------------------------------------------------------------------
        final_status = (
            ToolExecutionStatus.COMPLETED
            if raw_result.status.value in ("COMPLETED", "SUCCESS")
            else ToolExecutionStatus.FAILED
        )

        await self._repo.update_status(
            tool_exe,
            final_status.value,
            output=raw_result.output if isinstance(raw_result.output, (dict, list)) else {"text": str(raw_result.output)},
            errors=[e.model_dump() for e in raw_result.errors],
            duration_ms=duration_ms,
        )

        event_type = (
            EventType.TOOL_COMPLETED
            if final_status == ToolExecutionStatus.COMPLETED
            else EventType.TOOL_FAILED
        )
        await self._emit_tool_event(
            request.execution_id, event_type, request.request_id,
            {"tool_slug": tool_slug, "duration_ms": duration_ms},
        )

        # Build final result with observation IDs
        result = ToolExecutionResult(
            request_id=request.request_id,
            tool_execution_id=tool_exe.id,
            tool_slug=tool_slug,
            tool_version=tool_version,
            status=final_status,
            output=raw_result.output,
            observations=observations,
            artifact_ids=raw_result.artifact_ids,
            errors=raw_result.errors,
            usage=ToolUsage(duration_ms=duration_ms),
            duration_ms=duration_ms,
            attempt=request.attempt,
            started_at=tool_exe.started_at,
            completed_at=tool_exe.completed_at,
        )

        logger.info(
            "tool_execution_completed",
            tool_slug=tool_slug,
            status=final_status.value,
            duration_ms=duration_ms,
            observation_count=len(observations),
        )

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_timeout(
        self, request: ToolExecutionRequest, manifest: Any,
    ) -> int:
        """Resolve effective timeout: request override < manifest < ceiling."""
        candidates = [_MAX_CEILING_TIMEOUT_SECONDS]
        if manifest.limits.timeout_seconds:
            candidates.append(manifest.limits.timeout_seconds)
        if request.timeout_seconds:
            candidates.append(request.timeout_seconds)
        return min(candidates)

    async def _transition(
        self, tool_exe: Any, target: ToolExecutionStatus,
    ) -> None:
        """Validate and apply a status transition."""
        current = ToolExecutionStatus(tool_exe.status)
        validate_tool_execution_transition(current, target)
        await self._repo.update_status(tool_exe, target.value)

    async def _emit_tool_event(
        self,
        execution_id: str,
        event_type: EventType,
        request_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Emit a tool lifecycle event to the execution trajectory."""
        await self._kernel.emit_event(
            execution_id=execution_id,
            event_type=event_type,
            source="dsrt.tools.execution",
            payload=payload,
            request_id=request_id,
        )

    async def _fail_execution(
        self,
        tool_exe: Any,
        request: ToolExecutionRequest,
        start_time: float,
        *,
        error_code: str,
        error_message: str,
    ) -> ToolExecutionResult:
        """Handle a failed tool execution."""
        duration_ms = int((time.perf_counter() - start_time) * 1000)

        error = ToolExecutionError(
            code=error_code,
            message=error_message,
            retryable=error_code in ("TOOL_TIMEOUT", "TOOL_NETWORK_FAILURE", "TOOL_RATE_LIMITED"),
        )

        await self._repo.update_status(
            tool_exe,
            ToolExecutionStatus.FAILED.value,
            errors=[error.model_dump()],
            duration_ms=duration_ms,
        )

        await self._emit_tool_event(
            request.execution_id, EventType.TOOL_FAILED, request.request_id,
            {"tool_slug": request.tool_slug, "error_code": error_code, "error": error_message},
        )

        logger.warning(
            "tool_execution_failed",
            tool_slug=request.tool_slug,
            error_code=error_code,
            duration_ms=duration_ms,
        )

        return ToolExecutionResult(
            request_id=request.request_id,
            tool_execution_id=tool_exe.id,
            tool_slug=request.tool_slug,
            tool_version=request.tool_version or "unknown",
            status=ToolExecutionStatus.FAILED,
            output=None,
            observations=[],
            artifact_ids=[],
            errors=[error],
            usage=ToolUsage(duration_ms=duration_ms),
            duration_ms=duration_ms,
            attempt=request.attempt,
        )

    async def _cancel_execution(
        self,
        tool_exe: Any,
        request: ToolExecutionRequest,
        start_time: float,
    ) -> ToolExecutionResult:
        """Handle a cancelled tool execution."""
        duration_ms = int((time.perf_counter() - start_time) * 1000)

        try:
            current = ToolExecutionStatus(tool_exe.status)
            if current != ToolExecutionStatus.CANCELLING:
                validate_tool_execution_transition(current, ToolExecutionStatus.CANCELLING)
                await self._repo.update_status(tool_exe, ToolExecutionStatus.CANCELLING.value)
        except Exception:
            pass

        await self._repo.update_status(
            tool_exe,
            ToolExecutionStatus.CANCELLED.value,
            duration_ms=duration_ms,
        )

        await self._emit_tool_event(
            request.execution_id, EventType.TOOL_CANCELLED, request.request_id,
            {"tool_slug": request.tool_slug},
        )

        return ToolExecutionResult(
            request_id=request.request_id,
            tool_execution_id=tool_exe.id,
            tool_slug=request.tool_slug,
            tool_version=request.tool_version or "unknown",
            status=ToolExecutionStatus.CANCELLED,
            output=None,
            observations=[],
            artifact_ids=[],
            errors=[ToolExecutionError(code="TOOL_CANCELLED", message="Execution cancelled.")],
            usage=ToolUsage(duration_ms=duration_ms),
            duration_ms=duration_ms,
            attempt=request.attempt,
        )

    @staticmethod
    def _orm_to_result(tool_exe: Any) -> ToolExecutionResult:
        """Convert a persisted ToolExecution ORM to a ToolExecutionResult."""
        return ToolExecutionResult(
            request_id=tool_exe.request_id,
            tool_execution_id=tool_exe.id,
            tool_slug=tool_exe.tool_slug,
            tool_version=tool_exe.tool_version,
            status=ToolExecutionStatus(tool_exe.status),
            output=tool_exe.output,
            observations=[],
            artifact_ids=[],
            errors=[ToolExecutionError(**e) for e in (tool_exe.errors or [])],
            usage=ToolUsage(duration_ms=tool_exe.duration_ms),
            duration_ms=tool_exe.duration_ms,
            attempt=tool_exe.attempt,
            started_at=tool_exe.started_at,
            completed_at=tool_exe.completed_at,
        )