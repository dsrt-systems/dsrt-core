"""
Node Executor (C5 §21-27, §42-44, §65-67).

Executes individual plan nodes by:
  1. Resolving the agent (via C1 AgentRegistry)
  2. Building the SDK (via C3 build_agent_sdk)
  3. Compiling context (via C4 ContextEngine)
  4. Initializing and executing the agent (via C1 AgentAdapter)
  5. Validating output against the node's output_schema
  6. Emitting events into the execution trajectory
  7. Managing the node lifecycle (via NodeLifecycleManager)

The Node Executor does NOT:
  - Coordinate between nodes (Scheduler's job)
  - Make scheduling decisions (Scheduler's job)
  - Persist orchestration state (Orchestrator's job)
  - Handle retries across nodes (Recovery Manager's job, C5.9)

It handles the lifecycle of a SINGLE node execution.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import EventType, NodeStatus, NodeType
from schemas.domain.orchestration import PlanNode

from core.agents.adapter.adapter import AgentAdapter
from core.agents.registry import AgentRegistry
from core.api.errors.exceptions import DSRTError, NotFoundError
from core.kernel.cancellation import cancellation_manager
from core.kernel.kernel import ExecutionKernel
from core.observability.logging import get_logger
from core.orchestration.executor.lifecycle import NodeLifecycleManager
from core.repositories import (
    AgentRepository,
    CapabilityRepository,
    EventRepository,
    ExecutionRepository,
    TaskRepository,
)
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.orchestration import NodeExecutionORM
from sdk.agent.contract import (
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentInitializationRequest,
)
from sdk.agent.runtime.factory import build_agent_sdk


logger = get_logger("dsrt.orchestration.executor")


@dataclass
class NodeExecutionResult:
    """Result of executing a single node."""

    node_key: str
    node_execution_id: str
    status: str  # NodeStatus value
    output: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: int = 0
    resource_usage: dict[str, Any] = field(default_factory=dict)
    artifacts_created: list[str] = field(default_factory=list)


class NodeExecutor:
    """Executes individual plan nodes through the DSRT pipeline.

    Usage:
        executor = NodeExecutor(session, kernel, agent_registry)
        result = await executor.execute_node(
            node=plan_node,
            orchestration_execution_id="oex_...",
            task_id="tsk_...",
            organization_id="org_...",
            user_id="usr_...",
        )
    """

    def __init__(
        self,
        session: AsyncSession,
        kernel: ExecutionKernel,
        agent_registry: AgentRegistry,
    ) -> None:
        self._session = session
        self._kernel = kernel
        self._agent_registry = agent_registry
        self._lifecycle = NodeLifecycleManager()

    async def execute_node(
        self,
        node: PlanNode,
        orchestration_execution_id: str,
        plan_version_id: str,
        task_id: str,
        organization_id: str,
        user_id: str,
        node_inputs: dict[str, Any] | None = None,
        attempt: int = 1,
    ) -> NodeExecutionResult:
        """Execute a single plan node.

        This is the main entry point. It manages the full node lifecycle:
        PENDING → RUNNING → VERIFYING → COMPLETED (or FAILED).

        Args:
            node: The PlanNode to execute.
            orchestration_execution_id: Parent orchestration execution.
            plan_version_id: The plan version this node belongs to.
            task_id: The DSRT task ID.
            organization_id: The organization context.
            user_id: The user who initiated the task.
            node_inputs: Inputs from upstream dependencies.
            attempt: Current attempt number (for retries).

        Returns:
            NodeExecutionResult with status, output, and metrics.
        """
        start_time = time.perf_counter()
        node_exec_id = new_id(IdPrefix.NODE_EXECUTION)

        # Create NodeExecution record
        node_exec_orm = NodeExecutionORM(
            id=node_exec_id,
            orchestration_execution_id=orchestration_execution_id,
            plan_node_key=node.node_key,
            plan_version_id=plan_version_id,
            attempt=attempt,
            status=NodeStatus.RUNNING.value,
            agent_slug=node.agent_slug,
            agent_version=node.agent_version,
            input_reference=node_inputs,
            started_at=datetime.now(timezone.utc),
        )
        self._session.add(node_exec_orm)
        await self._session.flush()

        # Emit NODE_STARTED event
        await self._emit_event(
            orchestration_execution_id,
            EventType.AGENT_EXECUTION_STARTED,
            {
                "node_key": node.node_key,
                "node_type": node.node_type,
                "node_execution_id": node_exec_id,
                "attempt": attempt,
            },
        )

        try:
            # Dispatch based on node type
            if node.node_type == NodeType.AGENT_TASK.value:
                result = await self._execute_agent_task(
                    node=node,
                    node_exec_id=node_exec_id,
                    orchestration_execution_id=orchestration_execution_id,
                    task_id=task_id,
                    organization_id=organization_id,
                    user_id=user_id,
                    node_inputs=node_inputs or {},
                )
            elif node.node_type == NodeType.VERIFICATION.value:
                result = await self._execute_verification_node(
                    node=node,
                    node_exec_id=node_exec_id,
                    node_inputs=node_inputs or {},
                )
            elif node.node_type == NodeType.CHECKPOINT.value:
                result = await self._execute_checkpoint_node(
                    node=node,
                    node_exec_id=node_exec_id,
                )
            elif node.node_type == NodeType.MERGE.value:
                result = await self._execute_merge_node(
                    node=node,
                    node_exec_id=node_exec_id,
                    node_inputs=node_inputs or {},
                )
            elif node.node_type == NodeType.CONDITION.value:
                result = await self._execute_condition_node(
                    node=node,
                    node_exec_id=node_exec_id,
                    node_inputs=node_inputs or {},
                )
            elif node.node_type == NodeType.HUMAN_APPROVAL.value:
                result = await self._execute_approval_node(
                    node=node,
                    node_exec_id=node_exec_id,
                )
            else:
                result = NodeExecutionResult(
                    node_key=node.node_key,
                    node_execution_id=node_exec_id,
                    status=NodeStatus.FAILED.value,
                    error_code="UNSUPPORTED_NODE_TYPE",
                    error_message=f"Node type '{node.node_type}' is not supported.",
                )

        except DSRTError as e:
            result = NodeExecutionResult(
                node_key=node.node_key,
                node_execution_id=node_exec_id,
                status=NodeStatus.FAILED.value,
                error_code="NODE_EXECUTION_FAILED",
                error_message=str(e),
            )
        except Exception as e:
            logger.error(
                "node_execution_unexpected_error",
                node_key=node.node_key,
                error=str(e),
            )
            result = NodeExecutionResult(
                node_key=node.node_key,
                node_execution_id=node_exec_id,
                status=NodeStatus.FAILED.value,
                error_code="INTERNAL_ERROR",
                error_message=str(e),
            )

        # Finalize
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        result.duration_ms = duration_ms

        # Update NodeExecution record
        node_exec_orm.status = result.status
        node_exec_orm.output_reference = result.output
        node_exec_orm.error_code = result.error_code
        node_exec_orm.error_message = result.error_message
        node_exec_orm.completed_at = datetime.now(timezone.utc)
        node_exec_orm.resource_usage = result.resource_usage
        await self._session.flush()

        # Emit completion event
        event_type = (
            EventType.AGENT_EXECUTION_COMPLETED
            if result.status == NodeStatus.COMPLETED.value
            else EventType.AGENT_EXECUTION_FAILED
        )
        await self._emit_event(
            orchestration_execution_id,
            event_type,
            {
                "node_key": node.node_key,
                "node_execution_id": node_exec_id,
                "status": result.status,
                "duration_ms": duration_ms,
                "error_code": result.error_code,
            },
        )

        logger.info(
            "node_execution_completed",
            node_key=node.node_key,
            node_execution_id=node_exec_id,
            status=result.status,
            duration_ms=duration_ms,
        )

        return result

    # ------------------------------------------------------------------
    # Node Type Handlers
    # ------------------------------------------------------------------

    async def _execute_agent_task(
        self,
        node: PlanNode,
        node_exec_id: str,
        orchestration_execution_id: str,
        task_id: str,
        organization_id: str,
        user_id: str,
        node_inputs: dict[str, Any],
    ) -> NodeExecutionResult:
        """Execute an AGENT_TASK node (C5 §9).

        Pipeline:
          1. Resolve agent from registry
          2. Build SDK
          3. Initialize agent via AgentAdapter
          4. Execute agent
          5. Extract output
        """
        # 1. Resolve agent
        agent_slug = node.agent_slug
        if not agent_slug:
            # Try to resolve from capabilities (C5 §16-18)
            agent_slug = await self._resolve_agent_by_capability(
                node.required_capabilities,
            )
            if not agent_slug:
                return NodeExecutionResult(
                    node_key=node.node_key,
                    node_execution_id=node_exec_id,
                    status=NodeStatus.FAILED.value,
                    error_code="AGENT_NOT_FOUND",
                    error_message=(
                        f"No agent found for capabilities: "
                        f"{node.required_capabilities}"
                    ),
                )

        # 2. Resolve agent version
        try:
            agent_version = await self._agent_registry.resolve_agent_version(
                agent_slug, node.agent_version,
            )
        except NotFoundError as e:
            return NodeExecutionResult(
                node_key=node.node_key,
                node_execution_id=node_exec_id,
                status=NodeStatus.FAILED.value,
                error_code="AGENT_NOT_FOUND",
                error_message=str(e),
            )

        # 3. Build SDK
        sdk = build_agent_sdk(
            session=self._session,
            kernel=self._kernel,
            execution_id=orchestration_execution_id,
            task_id=task_id,
            organization_id=organization_id,
            user_id=user_id,
            agent_slug=agent_slug,
            agent_version=agent_version.version,
            agent_version_id=agent_version.id,
            agent_manifest=agent_version.manifest,
        )

        # 4. Initialize agent
        # Import the agent class dynamically
        agent_instance = self._load_agent_instance(agent_slug)
        if agent_instance is None:
            return NodeExecutionResult(
                node_key=node.node_key,
                node_execution_id=node_exec_id,
                status=NodeStatus.FAILED.value,
                error_code="AGENT_NOT_FOUND",
                error_message=f"Cannot load agent class for '{agent_slug}'.",
            )

        adapter = AgentAdapter(agent_instance)

        init_result = await adapter.initialize(
            sdk,
            AgentInitializationRequest(
                execution_id=orchestration_execution_id,
                task_id=task_id,
                organization_id=organization_id,
                agent_version_id=agent_version.id,
                sdk_version=sdk.sdk_version,
                contract_version=sdk.contract_version,
            ),
        )

        if init_result.status != "READY":
            return NodeExecutionResult(
                node_key=node.node_key,
                node_execution_id=node_exec_id,
                status=NodeStatus.FAILED.value,
                error_code="AGENT_INITIALIZATION_FAILED",
                error_message=init_result.message,
            )

        # 5. Check cancellation before execution
        cancel_token = cancellation_manager.get_token(
            orchestration_execution_id,
        )
        if cancel_token and cancel_token.is_set():
            await adapter.cancel()
            return NodeExecutionResult(
                node_key=node.node_key,
                node_execution_id=node_exec_id,
                status=NodeStatus.CANCELLED.value,
                error_code="EXECUTION_CANCELLED",
                error_message="Cancelled before node execution.",
            )

        # 6. Execute agent
        exec_result: AgentExecutionResult = await adapter.execute(
            AgentExecutionRequest(
                execution_id=orchestration_execution_id,
                task_id=task_id,
                objective=node.description or node.name,
                input_payload=node_inputs,
            )
        )

        # 7. Map result
        if exec_result.status == "COMPLETED":
            return NodeExecutionResult(
                node_key=node.node_key,
                node_execution_id=node_exec_id,
                status=NodeStatus.COMPLETED.value,
                output=exec_result.result_summary or {},
                artifacts_created=exec_result.artifacts_created or [],
            )
        elif exec_result.status == "CANCELLED":
            return NodeExecutionResult(
                node_key=node.node_key,
                node_execution_id=node_exec_id,
                status=NodeStatus.CANCELLED.value,
                error_code=exec_result.error_code,
                error_message=exec_result.error_message,
            )
        else:
            return NodeExecutionResult(
                node_key=node.node_key,
                node_execution_id=node_exec_id,
                status=NodeStatus.FAILED.value,
                error_code=exec_result.error_code or "AGENT_EXECUTION_FAILED",
                error_message=exec_result.error_message,
                output=exec_result.result_summary or {},
            )

    async def _execute_verification_node(
        self,
        node: PlanNode,
        node_exec_id: str,
        node_inputs: dict[str, Any],
    ) -> NodeExecutionResult:
        """Execute a VERIFICATION node (C5 §9).

        C5.6 v1: Pass-through verification that checks for required
        output fields. Full verification comes in C6.
        """
        # Check that upstream produced output
        if not node_inputs:
            return NodeExecutionResult(
                node_key=node.node_key,
                node_execution_id=node_exec_id,
                status=NodeStatus.COMPLETED.value,
                output={"verification": "PASSED", "note": "No inputs to verify."},
            )

        # Basic structural verification
        errors: list[str] = []
        if node.output_schema:
            for required_field in node.output_schema.get("required", []):
                if required_field not in node_inputs:
                    errors.append(f"Missing required field: {required_field}")

        if errors:
            return NodeExecutionResult(
                node_key=node.node_key,
                node_execution_id=node_exec_id,
                status=NodeStatus.FAILED.value,
                error_code="VERIFICATION_FAILED",
                error_message="; ".join(errors),
                output={"verification": "FAILED", "errors": errors},
            )

        return NodeExecutionResult(
            node_key=node.node_key,
            node_execution_id=node_exec_id,
            status=NodeStatus.COMPLETED.value,
            output={"verification": "PASSED", "inputs_checked": len(node_inputs)},
        )

    async def _execute_checkpoint_node(
        self,
        node: PlanNode,
        node_exec_id: str,
    ) -> NodeExecutionResult:
        """Execute a CHECKPOINT node (C5 §28-29).

        C5.6 v1: Records a checkpoint marker. Full checkpoint
        persistence comes in C5.9.
        """
        return NodeExecutionResult(
            node_key=node.node_key,
            node_execution_id=node_exec_id,
            status=NodeStatus.COMPLETED.value,
            output={"checkpoint": True, "node_execution_id": node_exec_id},
        )

    async def _execute_merge_node(
        self,
        node: PlanNode,
        node_exec_id: str,
        node_inputs: dict[str, Any],
    ) -> NodeExecutionResult:
        """Execute a MERGE node (C5 §45-46).

        Combines outputs from parallel upstream nodes.
        Default policy: CONFLICT_PRESERVING (append all, flag conflicts).
        """
        merge_policy = node.configuration.get(
            "merge_policy", "CONFLICT_PRESERVING",
        )

        merged: dict[str, Any] = {}
        sources: list[str] = []

        for key, value in node_inputs.items():
            sources.append(key)
            if isinstance(value, dict):
                for k, v in value.items():
                    if k in merged and merged[k] != v:
                        # Conflict detected — preserve both
                        if merge_policy == "CONFLICT_PRESERVING":
                            merged[k] = {
                                "CONFLICT": True,
                                "values": [merged[k], v],
                                "sources": sources,
                            }
                        else:
                            merged[k] = v  # Last-write-wins
                    else:
                        merged[k] = v
            else:
                merged[key] = value

        return NodeExecutionResult(
            node_key=node.node_key,
            node_execution_id=node_exec_id,
            status=NodeStatus.COMPLETED.value,
            output={
                "merged": merged,
                "merge_policy": merge_policy,
                "source_count": len(sources),
            },
        )

    async def _execute_condition_node(
        self,
        node: PlanNode,
        node_exec_id: str,
        node_inputs: dict[str, Any],
    ) -> NodeExecutionResult:
        """Execute a CONDITION node (C5 §47).

        Evaluates a structured condition against the shared state.
        Conditions use simple key-path lookups, NOT arbitrary code.
        """
        condition = node.configuration.get("condition", {})
        field_path = condition.get("field", "")
        operator = condition.get("operator", "==")
        expected = condition.get("value")

        # Navigate the field path in node_inputs
        actual = node_inputs
        for part in field_path.split("."):
            if isinstance(actual, dict) and part in actual:
                actual = actual[part]
            else:
                actual = None
                break

        # Evaluate
        result = False
        if operator == "==":
            result = actual == expected
        elif operator == "!=":
            result = actual != expected
        elif operator == ">":
            result = actual is not None and actual > expected
        elif operator == "<":
            result = actual is not None and actual < expected
        elif operator == ">=":
            result = actual is not None and actual >= expected
        elif operator == "<=":
            result = actual is not None and actual <= expected
        elif operator == "in":
            result = actual in expected if expected else False
        elif operator == "exists":
            result = actual is not None

        return NodeExecutionResult(
            node_key=node.node_key,
            node_execution_id=node_exec_id,
            status=NodeStatus.COMPLETED.value,
            output={
                "condition_result": result,
                "field": field_path,
                "operator": operator,
                "actual": actual,
                "expected": expected,
            },
        )

    async def _execute_approval_node(
        self,
        node: PlanNode,
        node_exec_id: str,
    ) -> NodeExecutionResult:
        """Execute a HUMAN_APPROVAL node (C5 §37-38).

        C5.6 v1: Returns a WAITING status. The orchestrator loop
        will pause until the approval is granted/rejected via API.
        Full integration with C3 ApprovalService comes in C5.11.
        """
        return NodeExecutionResult(
            node_key=node.node_key,
            node_execution_id=node_exec_id,
            status=NodeStatus.FAILED.value,  # Will be handled as WAITING by orchestrator
            error_code="APPROVAL_REQUIRED",
            error_message="Human approval required before proceeding.",
            output={
                "approval_required": True,
                "risk_level": node.configuration.get("risk_level", "HIGH"),
                "required_role": node.configuration.get("required_role", "admin"),
            },
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _resolve_agent_by_capability(
        self, capabilities: list[str],
    ) -> str | None:
        """Resolve an agent slug from required capabilities (C5 §16-18).

        Searches the AgentRegistry for an agent that provides all
        required capabilities. Returns the first match or None.
        """
        if not capabilities:
            return None

        try:
            agents = await self._agent_registry.list_agents()
            for agent in agents:
                agent_caps = set(agent.capabilities) if hasattr(agent, 'capabilities') else set()
                if set(capabilities).issubset(agent_caps):
                    return agent.slug if hasattr(agent, 'slug') else agent.id
        except Exception as e:
            logger.warning(
                "agent_capability_resolution_failed",
                capabilities=capabilities,
                error=str(e),
            )

        return None

    def _load_agent_instance(self, agent_slug: str) -> Any:
        """Load an agent class instance by slug.

        C5.6 v1: Supports the built-in research_intelligence agent.
        C5.6 v2: Dynamic loading from agent packages.
        """
        if agent_slug == "research_intelligence":
            try:
                from agents.research_intelligence.runtime.agent import (
                    ResearchIntelligenceAgent,
                )
                return ResearchIntelligenceAgent()
            except ImportError as e:
                logger.error(
                    "agent_import_failed",
                    agent_slug=agent_slug,
                    error=str(e),
                )
                return None

        logger.warning(
            "agent_class_not_found",
            agent_slug=agent_slug,
            note="Dynamic agent loading not yet implemented.",
        )
        return None

    async def _emit_event(
        self,
        execution_id: str,
        event_type: EventType,
        payload: dict[str, Any],
    ) -> None:
        """Emit an event into the execution trajectory."""
        try:
            await self._kernel.emit_event(
                execution_id=execution_id,
                event_type=event_type,
                source="dsrt.orchestration.executor",
                payload=payload,
            )
        except Exception as e:
            logger.warning(
                "node_executor_event_emission_failed",
                execution_id=execution_id,
                event_type=event_type.value,
                error=str(e),
            )