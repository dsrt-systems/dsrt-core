"""
ToolSDK Implementation (C3.7 — replaces C1 stub).

Bridge between the Agent's SDK interface (`sdk.tools.call`) and Core's
Tool Fabric (Router → Permission Engine → Execution Engine).

Agents never touch the underlying tool implementations, registry,
permission engine, or execution engine — they only see the normalized
SDKToolResult.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.agent import AgentManifest
from schemas.domain.enums import ToolExecutionStatus
from schemas.domain.task import TaskConstraints
from schemas.domain.tool import ToolExecutionRequest

from core.kernel.kernel import ExecutionKernel
from core.observability.logging import get_logger
from core.repositories.task_repository import TaskRepository
from core.repositories.tool_repository import ToolRepository
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.agent import AgentVersion as AgentVersionORM
from core.tools.errors import (
    ToolApprovalRequiredError,
    ToolNotFoundError,
    ToolPermissionDeniedError,
    ToolRuntimeError,
    ToolVersionUnavailableError,
)
from core.tools.execution.engine import ToolExecutionEngine
from core.tools.permissions.engine import ToolPermissionEngine
from core.tools.permissions.policies import OrgToolPolicy, TaskToolPolicy
from core.tools.registry.registry import ToolRegistry
from core.tools.router.router import ToolRouter
from sdk.agent.interfaces.tools import SDKToolResult


logger = get_logger("sdk.tools")


class ToolSDKImpl:
    """Concrete implementation of ToolSDK backed by the DSRT Tool Fabric."""

    def __init__(
        self,
        session: AsyncSession,
        kernel: ExecutionKernel,
        execution_id: str,
        task_id: str,
        organization_id: str,
        agent_slug: str,
        agent_version: str,
        agent_version_id: str,
        agent_manifest: AgentManifest | None = None,
    ) -> None:
        self._session = session
        self._kernel = kernel
        self._execution_id = execution_id
        self._task_id = task_id
        self._organization_id = organization_id
        self._agent_slug = agent_slug
        self._agent_version = agent_version
        self._agent_version_id = agent_version_id
        self._agent_manifest = agent_manifest
        self._current_tool_calls = 0

    async def call(
        self, tool_slug: str, arguments: dict[str, Any],
    ) -> SDKToolResult:
        """Invoke a tool via the complete Tool Fabric pipeline."""
        start_time = time.perf_counter()
        request_id = new_id(IdPrefix.REQUEST)

        # --- 1. Lazy load agent manifest from DB if None ---
        if self._agent_manifest is None:
            try:
                stmt = select(AgentVersionORM).where(AgentVersionORM.id == self._agent_version_id)
                res = await self._session.execute(stmt)
                ver_orm = res.scalar_one_or_none()
                if ver_orm:
                    if isinstance(ver_orm.manifest, dict):
                        self._agent_manifest = AgentManifest.model_validate(ver_orm.manifest)
                    else:
                        self._agent_manifest = ver_orm.manifest
            except Exception as e:
                logger.warning("tool_sdk_lazy_manifest_load_failed", error=str(e))

        # --- Guard: agent manifest is required for permission evaluation ---
        if self._agent_manifest is None:
            logger.warning(
                "tool_call_missing_agent_manifest",
                tool_slug=tool_slug,
                agent_slug=self._agent_slug,
            )
            return SDKToolResult(
                tool_slug=tool_slug,
                status="FAILED",
                output=None,
                error_code="AGENT_MANIFEST_MISSING",
                error_message="Agent manifest not available for permission evaluation.",
            )

        # --- Build repositories & services ---
        tool_repo = ToolRepository(self._session)
        task_repo = TaskRepository(self._session)
        registry = ToolRegistry(tool_repo)

        # Load task constraints
        task_constraints: TaskConstraints | None = None
        task_orm = await task_repo.get_by_id(self._task_id)
        if task_orm and task_orm.constraints:
            try:
                task_constraints = TaskConstraints.model_validate(task_orm.constraints)
            except Exception:
                task_constraints = None

        permission_engine = ToolPermissionEngine(
            org_policy=OrgToolPolicy(),
            task_policy=TaskToolPolicy(),
        )
        router = ToolRouter(
            registry=registry,
            permission_engine=permission_engine,
        )

        # --- Route the request ---
        try:
            route = await router.route(
                tool_slug=tool_slug,
                agent_manifest=self._agent_manifest,
                organization_id=self._organization_id,
                task_constraints=task_constraints,
                current_tool_calls=self._current_tool_calls,
                request_id=request_id,
            )
        except ToolNotFoundError as e:
            return self._to_sdk_result(
                tool_slug, "DENIED", None,
                error_code="TOOL_NOT_FOUND",
                error_message=str(e),
                duration_ms=int((time.perf_counter() - start_time) * 1000),
            )
        except ToolVersionUnavailableError as e:
            return self._to_sdk_result(
                tool_slug, "DENIED", None,
                error_code="TOOL_VERSION_UNAVAILABLE",
                error_message=str(e),
                duration_ms=int((time.perf_counter() - start_time) * 1000),
            )
        except ToolPermissionDeniedError as e:
            return self._to_sdk_result(
                tool_slug, "DENIED", None,
                error_code="TOOL_PERMISSION_DENIED",
                error_message=str(e),
                duration_ms=int((time.perf_counter() - start_time) * 1000),
            )
        except ToolApprovalRequiredError as e:
            return self._to_sdk_result(
                tool_slug, "DENIED", None,
                error_code="TOOL_APPROVAL_REQUIRED",
                error_message=str(e),
                duration_ms=int((time.perf_counter() - start_time) * 1000),
            )
        except Exception as e:
            logger.exception("tool_routing_unexpected_error", tool_slug=tool_slug)
            return self._to_sdk_result(
                tool_slug, "FAILED", None,
                error_code="TOOL_RUNTIME_FAILURE",
                error_message=f"Routing failed: {e}",
                duration_ms=int((time.perf_counter() - start_time) * 1000),
            )

        # --- Build canonical tool execution request ---
        tool_request = ToolExecutionRequest(
            request_id=request_id,
            tool_slug=tool_slug,
            tool_version=route.tool_version,
            execution_id=self._execution_id,
            task_id=self._task_id,
            organization_id=self._organization_id,
            agent_slug=self._agent_slug,
            agent_version=self._agent_version,
            arguments=arguments,
            environment_id=route.environment_id,
            attempt=1,
        )

        # --- Execute via Execution Engine ---
        engine = ToolExecutionEngine(session=self._session, kernel=self._kernel)
        try:
            result = await engine.execute(request=tool_request, route=route)
        except ToolRuntimeError as e:
            return self._to_sdk_result(
                tool_slug, "FAILED", None,
                error_code="TOOL_RUNTIME_FAILURE",
                error_message=str(e),
                duration_ms=int((time.perf_counter() - start_time) * 1000),
            )
        except Exception as e:
            logger.exception("tool_execution_unexpected_error", tool_slug=tool_slug)
            return self._to_sdk_result(
                tool_slug, "FAILED", None,
                error_code="TOOL_RUNTIME_FAILURE",
                error_message=f"Execution failed: {e}",
                duration_ms=int((time.perf_counter() - start_time) * 1000),
            )

        # Track tool call for subsequent permission checks
        self._current_tool_calls += 1

        # --- Normalize to SDK result ---
        sdk_status = self._map_status(result.status)
        error_code = result.errors[0].code if result.errors else None
        error_message = result.errors[0].message if result.errors else None

        return SDKToolResult(
            tool_slug=tool_slug,
            status=sdk_status,
            output=result.output,
            duration_ms=result.duration_ms,
            error_code=error_code,
            error_message=error_message,
            metadata={
                "tool_execution_id": result.tool_execution_id,
                "tool_version": result.tool_version,
                "observation_count": len(result.observations),
                "artifact_ids": result.artifact_ids,
            },
        )

    async def available_tools(self) -> list[str]:
        """List tool slugs available to this agent under current policy."""
        tool_repo = ToolRepository(self._session)
        registry = ToolRegistry(tool_repo)
        tools = await registry.list_tools(status="ACTIVE")
        return [t.slug for t in tools]

    # --- Helpers ---

    @staticmethod
    def _map_status(status: ToolExecutionStatus) -> str:
        """Map ToolExecutionStatus to SDK status strings."""
        if status == ToolExecutionStatus.COMPLETED:
            return "SUCCESS"
        if status == ToolExecutionStatus.CANCELLED:
            return "CANCELLED"
        if status == ToolExecutionStatus.FAILED:
            return "FAILED"
        return "FAILED"

    @staticmethod
    def _to_sdk_result(
        tool_slug: str,
        status: str,
        output: Any,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        duration_ms: int = 0,
    ) -> SDKToolResult:
        return SDKToolResult(
            tool_slug=tool_slug,
            status=status,
            output=output,
            duration_ms=duration_ms,
            error_code=error_code,
            error_message=error_message,
        )