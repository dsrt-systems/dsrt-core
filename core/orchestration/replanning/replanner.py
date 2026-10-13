"""
Replanner (C5 §33-36, §56).

Creates new plan versions when the current plan becomes infeasible.

Replanning Trigger Conditions (C5 §34):
  - Critical node fails (after retries exhausted)
  - Required resource disappears
  - Dependency becomes impossible
  - New information invalidates plan
  - Budget becomes insufficient
  - Constraint changes
  - User changes objective
  - Verification fails
  - Agent recommends replanning
  - World state changes

Replanning Rules (C5 §35):
  - Never silently replace history
  - Plan v1 and Plan v2 both persist
  - Every replan is recorded in ReplanORM

Partial Replanning (C5 §36):
  - Only replace the failed subtree
  - Preserve completed nodes
  - Reconnect preserved nodes to new subtree
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import EventType, NodeStatus, PlanStatus
from schemas.domain.orchestration import (
    PlanConstraints,
    PlanDependency,
    PlanNode,
)

from core.kernel.kernel import ExecutionKernel
from core.observability.logging import get_logger
from core.orchestration.graph.graph import GraphEdge, GraphNode, TaskGraph
from core.orchestration.planner.validator import PlanValidationResult, PlanValidator
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.orchestration import (
    NodeExecutionORM,
    OrchestrationExecutionORM,
    PlanDependencyORM,
    PlanNodeORM,
    PlanORM,
    PlanVersionORM,
)
from core.storage.models.orchestration_state import ReplanORM


logger = get_logger("dsrt.orchestration.replanning")


@dataclass
class ReplanRequest:
    """A request to replan an execution (C5 §34)."""

    orchestration_execution_id: str
    plan_id: str
    current_plan_version_id: str

    # What triggered the replan
    trigger: str  # e.g., "NODE_FAILED", "BUDGET_EXHAUSTED", "USER_REQUEST"
    reason: str

    # Which nodes failed and need replacement
    failed_node_keys: list[str] = field(default_factory=list)

    # Optional: new nodes/dependencies to replace the failed subtree
    # If empty, the Replanner will generate a default bypass
    replacement_nodes: list[PlanNode] = field(default_factory=list)
    replacement_dependencies: list[PlanDependency] = field(default_factory=list)

    # Updated constraints (if any)
    updated_constraints: PlanConstraints | None = None


@dataclass
class ReplanResult:
    """Result of a replanning operation."""

    success: bool
    new_plan_version_id: str | None = None
    replan_id: str | None = None
    preserved_node_keys: list[str] = field(default_factory=list)
    affected_node_keys: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Replanner:
    """Creates new plan versions when the current plan becomes infeasible.

    Architecture (C5 §33-36):
      1. Identify failed nodes and their downstream dependents
      2. Identify completed nodes to preserve
      3. Extract the failed subtree
      4. Generate replacement nodes (or use provided ones)
      5. Reconnect preserved nodes to replacement subtree
      6. Validate the new plan
      7. Persist as a new PlanVersion (immutable, Invariant 4)
      8. Record the replan in ReplanORM (Invariant 10)
      9. Update the OrchestrationExecution to use the new version
     10. Emit events

    The Replanner does NOT execute the new plan — that's the
    Orchestrator's job after receiving the ReplanResult.
    """

    def __init__(
        self,
        session: AsyncSession,
        kernel: ExecutionKernel | None = None,
        validator: PlanValidator | None = None,
    ) -> None:
        self._session = session
        self._kernel = kernel
        self._validator = validator or PlanValidator()

    async def replan(
        self, request: ReplanRequest,
    ) -> ReplanResult:
        """Execute the full replanning pipeline.

        Returns:
            ReplanResult with the new plan version ID if successful.
        """
        replan_id = new_id(IdPrefix.REPLAN)

        logger.info(
            "replan_started",
            replan_id=replan_id,
            execution_id=request.orchestration_execution_id,
            trigger=request.trigger,
            reason=request.reason,
            failed_nodes=request.failed_node_keys,
        )

        # 1. Load current plan version and its nodes/dependencies
        current_version = await self._load_plan_version(
            request.current_plan_version_id,
        )
        if not current_version:
            return ReplanResult(
                success=False,
                errors=[
                    f"Plan version '{request.current_plan_version_id}' not found."
                ],
            )

        current_nodes = await self._load_plan_nodes(
            request.current_plan_version_id,
        )
        current_deps = await self._load_plan_dependencies(
            request.current_plan_version_id,
        )

        # 2. Load node execution statuses
        node_statuses = await self._load_node_statuses(
            request.orchestration_execution_id,
        )

        # 3. Classify nodes: completed (preserve) vs affected (replace)
        completed_keys = {
            k for k, s in node_statuses.items()
            if s == NodeStatus.COMPLETED.value
        }
        failed_keys = set(request.failed_node_keys)

        # Build the current graph to find downstream dependents
        graph = self._build_graph(current_nodes, current_deps)

        # All nodes downstream of failed nodes are also affected
        affected_keys = set(failed_keys)
        for fk in failed_keys:
            if fk in graph:
                affected_keys.update(graph.get_all_downstream(fk))

        # Nodes to preserve: completed AND not affected
        preserved_keys = completed_keys - affected_keys

        # Nodes that are neither completed nor affected (pending/ready)
        # These may also need to be reconnected
        pending_keys = (
            set(graph.node_keys) - completed_keys - affected_keys
        )

        logger.info(
            "replan_node_classification",
            replan_id=replan_id,
            preserved=sorted(preserved_keys),
            affected=sorted(affected_keys),
            pending=sorted(pending_keys),
        )

        # 4. Build replacement nodes
        if request.replacement_nodes:
            new_nodes = request.replacement_nodes
            new_deps = request.replacement_dependencies
        else:
            new_nodes, new_deps = self._generate_default_replacement(
                failed_keys=failed_keys,
                affected_keys=affected_keys,
                preserved_keys=preserved_keys,
                current_nodes=current_nodes,
                current_deps=current_deps,
            )

        # 5. Assemble the full new plan:
        #    preserved nodes + pending nodes + replacement nodes
        all_new_nodes: list[PlanNode] = []
        all_new_deps: list[PlanDependency] = []

        # Add preserved nodes (unchanged)
        preserved_node_keys_in_new: set[str] = set()
        for node in current_nodes:
            if node.node_key in preserved_keys:
                all_new_nodes.append(node)
                preserved_node_keys_in_new.add(node.node_key)

        # Add pending nodes (unchanged, but may need reconnection)
        for node in current_nodes:
            if node.node_key in pending_keys:
                all_new_nodes.append(node)

        # Add replacement nodes
        replacement_keys: set[str] = set()
        for node in new_nodes:
            all_new_nodes.append(node)
            replacement_keys.add(node.node_key)

        # 6. Rebuild dependencies
        # Keep dependencies between preserved/pending nodes
        for dep in current_deps:
            src_preserved = dep.source_node_key in (preserved_keys | pending_keys)
            tgt_preserved = dep.target_node_key in (preserved_keys | pending_keys)
            if src_preserved and tgt_preserved:
                all_new_deps.append(dep)

        # Add replacement dependencies
        for dep in new_deps:
            all_new_deps.append(dep)

        # Reconnect: if a preserved node was a dependency of an affected node,
        # and the replacement has a node that should receive that input,
        # add the edge
        for dep in current_deps:
            if (
                dep.source_node_key in preserved_keys
                and dep.target_node_key in affected_keys
            ):
                # Find replacement nodes that have no incoming edges
                # and connect them to the preserved source
                for rnode in new_nodes:
                    has_incoming = any(
                        d.target_node_key == rnode.node_key
                        for d in new_deps
                    )
                    if not has_incoming:
                        all_new_deps.append(PlanDependency(
                            source_node_key=dep.source_node_key,
                            target_node_key=rnode.node_key,
                            dependency_type=dep.dependency_type,
                        ))

        # Reconnect: if a replacement node should feed into a pending node
        for dep in current_deps:
            if (
                dep.source_node_key in affected_keys
                and dep.target_node_key in pending_keys
            ):
                # Find replacement nodes that have no outgoing edges
                for rnode in new_nodes:
                    has_outgoing = any(
                        d.source_node_key == rnode.node_key
                        for d in (new_deps + all_new_deps)
                    )
                    if not has_outgoing:
                        all_new_deps.append(PlanDependency(
                            source_node_key=rnode.node_key,
                            target_node_key=dep.target_node_key,
                            dependency_type=dep.dependency_type,
                        ))

        # 7. Validate the new plan
        constraints = request.updated_constraints or PlanConstraints()
        validation = self._validator.validate(
            nodes=all_new_nodes,
            dependencies=all_new_deps,
            constraints=constraints,
        )

        if not validation.valid:
            logger.warning(
                "replan_validation_failed",
                replan_id=replan_id,
                errors=validation.errors,
            )
            return ReplanResult(
                success=False,
                errors=validation.errors,
                warnings=validation.warnings,
                preserved_node_keys=sorted(preserved_keys),
                affected_node_keys=sorted(affected_keys),
            )

        # 8. Persist new PlanVersion (Invariant 4: immutable)
        new_version_number = current_version.version + 1
        graph_hash = (
            validation.graph.compute_hash()
            if validation.graph
            else ""
        )

        new_version_orm = PlanVersionORM(
            id=new_id(IdPrefix.PLAN_VERSION),
            plan_id=request.plan_id,
            version=new_version_number,
            planner_model=None,
            planner_configuration={
                "replan_trigger": request.trigger,
                "replan_reason": request.reason,
                "replan_id": replan_id,
                "previous_version_id": request.current_plan_version_id,
            },
            graph_hash=graph_hash,
            reason=f"Replan: {request.reason}",
        )
        self._session.add(new_version_orm)
        await self._session.flush()

        # Persist new nodes
        for node in all_new_nodes:
            node_orm = PlanNodeORM(
                id=new_id(IdPrefix.PLAN_NODE),
                plan_version_id=new_version_orm.id,
                node_key=node.node_key,
                name=node.name,
                description=node.description,
                node_type=node.node_type,
                agent_slug=node.agent_slug,
                agent_version=node.agent_version,
                required_capabilities=node.required_capabilities,
                input_schema=node.input_schema,
                output_schema=node.output_schema,
                retry_policy=node.retry_policy,
                timeout_seconds=node.timeout_seconds,
                verification_policy=node.verification_policy,
                resource_limits=node.resource_limits,
                configuration=node.configuration,
            )
            self._session.add(node_orm)

        # Persist new dependencies
        for dep in all_new_deps:
            dep_orm = PlanDependencyORM(
                id=new_id(IdPrefix.PLAN_DEPENDENCY),
                plan_version_id=new_version_orm.id,
                source_node_key=dep.source_node_key,
                target_node_key=dep.target_node_key,
                dependency_type=dep.dependency_type,
                condition=dep.condition,
            )
            self._session.add(dep_orm)

        # 9. Mark old plan version as SUPERSEDED
        current_version_orm = await self._load_plan_version_orm(
            request.current_plan_version_id,
        )
        if current_version_orm:
            # Update the parent plan's current_version pointer
            plan_stmt = select(PlanORM).where(
                PlanORM.id == request.plan_id,
            )
            plan_result = await self._session.execute(plan_stmt)
            plan_orm = plan_result.scalar_one_or_none()
            if plan_orm:
                plan_orm.current_version = new_version_number

        # 10. Record the replan (Invariant 10: history preserved)
        replan_orm = ReplanORM(
            id=replan_id,
            orchestration_execution_id=request.orchestration_execution_id,
            previous_plan_version_id=request.current_plan_version_id,
            new_plan_version_id=new_version_orm.id,
            trigger=request.trigger,
            reason=request.reason,
            affected_nodes=sorted(affected_keys),
            preserved_nodes=sorted(preserved_keys),
        )
        self._session.add(replan_orm)
        await self._session.flush()

        # 11. Update the orchestration execution to use the new plan version
        exec_stmt = (
            select(OrchestrationExecutionORM)
            .where(
                OrchestrationExecutionORM.id
                == request.orchestration_execution_id
            )
        )
        exec_result = await self._session.execute(exec_stmt)
        exec_orm = exec_result.scalar_one_or_none()
        if exec_orm:
            exec_orm.plan_version_id = new_version_orm.id

        await self._session.flush()

        # 12. Emit event
        await self._emit_event(
            request.orchestration_execution_id,
            EventType.AGENT_EVENT,
            {
                "replan_event": "PLAN_REPLANNED",
                "replan_id": replan_id,
                "trigger": request.trigger,
                "previous_version": current_version.version,
                "new_version": new_version_number,
                "preserved_nodes": sorted(preserved_keys),
                "affected_nodes": sorted(affected_keys),
                "new_node_count": len(all_new_nodes),
            },
        )

        logger.info(
            "replan_completed",
            replan_id=replan_id,
            execution_id=request.orchestration_execution_id,
            previous_version=current_version.version,
            new_version=new_version_number,
            preserved=len(preserved_keys),
            affected=len(affected_keys),
            new_nodes=len(all_new_nodes),
        )

        return ReplanResult(
            success=True,
            new_plan_version_id=new_version_orm.id,
            replan_id=replan_id,
            preserved_node_keys=sorted(preserved_keys),
            affected_node_keys=sorted(affected_keys),
            warnings=validation.warnings,
        )

    # ------------------------------------------------------------------
    # Default Replacement Generation
    # ------------------------------------------------------------------

    def _generate_default_replacement(
        self,
        failed_keys: set[str],
        affected_keys: set[str],
        preserved_keys: set[str],
        current_nodes: list[PlanNode],
        current_deps: list[PlanDependency],
    ) -> tuple[list[PlanNode], list[PlanDependency]]:
        """Generate a default replacement for the failed subtree.

        Strategy: Create a single retry node per failed root that
        re-executes the failed work, then reconnects to the downstream
        pending nodes.

        For more sophisticated replanning, the model-assisted planner
        (C5.4) can be invoked to generate a better replacement.
        """
        new_nodes: list[PlanNode] = []
        new_deps: list[PlanDependency] = []

        # Find the "root" failed nodes (failed nodes whose dependencies
        # are all preserved or also failed)
        root_failed = set()
        for fk in failed_keys:
            deps_of_fk = {
                d.source_node_key
                for d in current_deps
                if d.target_node_key == fk
            }
            # If all deps are either preserved or also failed, this is a root
            if deps_of_fk.issubset(preserved_keys | failed_keys):
                root_failed.add(fk)

        if not root_failed:
            root_failed = failed_keys  # Fallback: treat all as roots

        for fk in sorted(root_failed):
            # Find the original node to copy its configuration
            original = next(
                (n for n in current_nodes if n.node_key == fk), None,
            )

            retry_key = f"{fk}_retry"
            retry_node = PlanNode(
                node_key=retry_key,
                name=f"Retry: {original.name if original else fk}",
                description=(
                    f"Re-execution of '{fk}' after failure. "
                    f"Original: {original.description if original else ''}"
                ),
                node_type=original.node_type if original else "AGENT_TASK",
                agent_slug=original.agent_slug if original else None,
                agent_version=original.agent_version if original else None,
                required_capabilities=(
                    original.required_capabilities if original else []
                ),
                input_schema=original.input_schema if original else {},
                output_schema=original.output_schema if original else {},
                retry_policy={
                    "max_attempts": 2,
                    "backoff": "exponential",
                },
                configuration={
                    "is_retry": True,
                    "original_node_key": fk,
                },
            )
            new_nodes.append(retry_node)

        # Chain retry nodes if there are multiple
        retry_keys = [n.node_key for n in new_nodes]
        for i in range(1, len(retry_keys)):
            new_deps.append(PlanDependency(
                source_node_key=retry_keys[i - 1],
                target_node_key=retry_keys[i],
                dependency_type="HARD",
            ))

        return new_nodes, new_deps

    # ------------------------------------------------------------------
    # Data Loading Helpers
    # ------------------------------------------------------------------

    async def _load_plan_version(
        self, plan_version_id: str,
    ) -> PlanVersionORM | None:
        """Load a PlanVersionORM by ID."""
        stmt = select(PlanVersionORM).where(
            PlanVersionORM.id == plan_version_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def _load_plan_version_orm(
        self, plan_version_id: str,
    ) -> PlanVersionORM | None:
        """Alias for _load_plan_version."""
        return await self._load_plan_version(plan_version_id)

    async def _load_plan_nodes(
        self, plan_version_id: str,
    ) -> list[PlanNode]:
        """Load all PlanNodes for a version as domain schemas."""
        stmt = (
            select(PlanNodeORM)
            .where(PlanNodeORM.plan_version_id == plan_version_id)
            .order_by(PlanNodeORM.node_key.asc())
        )
        result = await self._session.execute(stmt)
        orms = list(result.scalars().all())

        return [
            PlanNode(
                node_key=o.node_key,
                name=o.name,
                description=o.description,
                node_type=o.node_type,
                agent_slug=o.agent_slug,
                agent_version=o.agent_version,
                required_capabilities=o.required_capabilities or [],
                input_schema=o.input_schema or {},
                output_schema=o.output_schema or {},
                retry_policy=o.retry_policy or {},
                timeout_seconds=o.timeout_seconds,
                verification_policy=o.verification_policy,
                resource_limits=o.resource_limits or {},
                configuration=o.configuration or {},
            )
            for o in orms
        ]

    async def _load_plan_dependencies(
        self, plan_version_id: str,
    ) -> list[PlanDependency]:
        """Load all PlanDependencies for a version as domain schemas."""
        stmt = select(PlanDependencyORM).where(
            PlanDependencyORM.plan_version_id == plan_version_id,
        )
        result = await self._session.execute(stmt)
        orms = list(result.scalars().all())

        return [
            PlanDependency(
                source_node_key=o.source_node_key,
                target_node_key=o.target_node_key,
                dependency_type=o.dependency_type,
                condition=o.condition,
            )
            for o in orms
        ]

    async def _load_node_statuses(
        self, orchestration_execution_id: str,
    ) -> dict[str, str]:
        """Load the latest status for each node key in an execution."""
        stmt = (
            select(NodeExecutionORM)
            .where(
                NodeExecutionORM.orchestration_execution_id
                == orchestration_execution_id,
            )
            .order_by(NodeExecutionORM.created_at.desc())
        )
        result = await self._session.execute(stmt)
        orms = list(result.scalars().all())

        # Take the latest status per node key
        statuses: dict[str, str] = {}
        for o in orms:
            if o.plan_node_key not in statuses:
                statuses[o.plan_node_key] = o.status
        return statuses

    def _build_graph(
        self,
        nodes: list[PlanNode],
        deps: list[PlanDependency],
    ) -> TaskGraph:
        """Build a TaskGraph from plan nodes and dependencies."""
        graph = TaskGraph()
        for node in nodes:
            graph.add_node(GraphNode(
                key=node.node_key,
                node_type=node.node_type,
                agent_slug=node.agent_slug,
                required_capabilities=tuple(node.required_capabilities),
            ))
        for dep in deps:
            if dep.source_node_key in graph and dep.target_node_key in graph:
                graph.add_edge(GraphEdge(
                    source=dep.source_node_key,
                    target=dep.target_node_key,
                    dependency_type=dep.dependency_type,
                    condition=dep.condition,
                ))
        return graph

    # ------------------------------------------------------------------
    # Event Emission
    # ------------------------------------------------------------------

    async def _emit_event(
        self,
        execution_id: str,
        event_type: EventType,
        payload: dict[str, Any],
    ) -> None:
        """Emit a replan event into the execution trajectory."""
        if not self._kernel:
            return
        try:
            await self._kernel.emit_event(
                execution_id=execution_id,
                event_type=event_type,
                source="dsrt.orchestration.replanning",
                payload=payload,
            )
        except Exception as e:
            logger.warning(
                "replan_event_emission_failed",
                execution_id=execution_id,
                error=str(e),
            )