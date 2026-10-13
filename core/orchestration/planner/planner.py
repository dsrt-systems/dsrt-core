"""
Orchestration Planner (C5 §13, §61-64).

Converts objectives into validated, persisted Plans.

Architecture (C5 §61):
  Planner → proposes graph → deterministic validation → persist

The planner can be model-assisted (LLM generates nodes) or explicit
(user provides nodes). In both cases, the PlanValidator (C5 §14)
deterministically validates the result before persistence.

The planner does NOT execute anything (C5 §61).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import PlanStatus
from schemas.domain.orchestration import (
    Plan,
    PlanConstraints,
    PlanDependency,
    PlanNode,
    PlanRequest,
    PlanVersion,
)

from core.kernel.fingerprint import content_hash
from core.observability.logging import get_logger
from core.orchestration.graph.graph import TaskGraph
from core.orchestration.planner.prompts import (
    build_planning_prompt,
    build_repair_prompt,
)
from core.orchestration.planner.validator import PlanValidationResult, PlanValidator
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.orchestration import (
    PlanDependencyORM,
    PlanNodeORM,
    PlanORM,
    PlanVersionORM,
)


logger = get_logger("dsrt.orchestration.planner")


class Planner:
    """Orchestration Planner — creates validated plans from objectives.

    Supports two modes:
      1. Explicit: User provides nodes and dependencies in the PlanRequest.
      2. Model-assisted: LLM generates nodes from the objective (C5 §13).

    In both modes, the PlanValidator deterministically validates the result.
    """

    def __init__(
        self,
        session: AsyncSession,
        validator: PlanValidator | None = None,
        max_repair_attempts: int = 2,
    ) -> None:
        self._session = session
        self._validator = validator or PlanValidator()
        self._max_repair_attempts = max_repair_attempts

    async def create_plan(
        self,
        request: PlanRequest,
        organization_id: str,
    ) -> tuple[PlanORM, PlanVersionORM, PlanValidationResult]:
        """Create a plan for a task.

        If request contains nodes, uses explicit mode.
        If request has no nodes, generates a default single-agent plan.

        Returns:
            (PlanORM, PlanVersionORM, PlanValidationResult)
        """
        # 1. Create Plan record
        plan_orm = PlanORM(
            id=new_id(IdPrefix.PLAN),
            task_id=request.task_id,
            organization_id=organization_id,
            current_version=0,
            status=PlanStatus.CREATED.value,
            objective=request.objective,
        )
        self._session.add(plan_orm)
        await self._session.flush()

        logger.info(
            "plan_created",
            plan_id=plan_orm.id,
            task_id=request.task_id,
            objective=request.objective[:100],
        )

        # 2. Generate or use provided nodes
        if request.nodes:
            nodes = request.nodes
            dependencies = request.dependencies
        else:
            nodes, dependencies = self._generate_default_plan(request)

        # 3. Validate
        validation = self._validator.validate(
            nodes=nodes,
            dependencies=dependencies,
            constraints=request.constraints,
        )

        # 4. If invalid and we have a model, attempt repair
        if not validation.valid and self._max_repair_attempts > 0:
            for attempt in range(self._max_repair_attempts):
                logger.info(
                    "plan_repair_attempt",
                    plan_id=plan_orm.id,
                    attempt=attempt + 1,
                    errors=len(validation.errors),
                )
                nodes, dependencies = self._attempt_repair(
                    request, nodes, dependencies, validation,
                )
                validation = self._validator.validate(
                    nodes=nodes,
                    dependencies=dependencies,
                    constraints=request.constraints,
                )
                if validation.valid:
                    break

        # 5. Persist PlanVersion
        if validation.valid:
            plan_orm.status = PlanStatus.VALID.value
        else:
            plan_orm.status = PlanStatus.INVALID.value

        # Build graph hash for versioning (C5 §64)
        graph = validation.graph
        graph_hash = graph.compute_hash() if graph else content_hash(
            str([n.node_key for n in nodes])
        )

        version_orm = PlanVersionORM(
            id=new_id(IdPrefix.PLAN_VERSION),
            plan_id=plan_orm.id,
            version=1,
            planner_model=None,
            planner_configuration=request.metadata,
            graph_hash=graph_hash,
            reason="Initial plan creation",
        )
        self._session.add(version_orm)
        await self._session.flush()

        # 6. Persist nodes
        for node in nodes:
            node_orm = PlanNodeORM(
                id=new_id(IdPrefix.PLAN_NODE),
                plan_version_id=version_orm.id,
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

        # 7. Persist dependencies
        for dep in dependencies:
            dep_orm = PlanDependencyORM(
                id=new_id(IdPrefix.PLAN_DEPENDENCY),
                plan_version_id=version_orm.id,
                source_node_key=dep.source_node_key,
                target_node_key=dep.target_node_key,
                dependency_type=dep.dependency_type,
                condition=dep.condition,
            )
            self._session.add(dep_orm)

        # 8. Update plan version pointer
        plan_orm.current_version = 1
        await self._session.flush()

        logger.info(
            "plan_version_created",
            plan_id=plan_orm.id,
            version_id=version_orm.id,
            version=1,
            status=plan_orm.status,
            node_count=len(nodes),
            dependency_count=len(dependencies),
            graph_hash=graph_hash[:16],
            valid=validation.valid,
        )

        return plan_orm, version_orm, validation

    async def create_plan_version(
        self,
        plan_id: str,
        nodes: list[PlanNode],
        dependencies: list[PlanDependency],
        constraints: PlanConstraints,
        reason: str = "Replan",
    ) -> tuple[PlanVersionORM | None, PlanValidationResult]:
        """Create a new version of an existing plan (C5 §33-36, §64).

        Used by the Replanner (C5.10). The previous version remains immutable.

        Returns:
            (PlanVersionORM or None if invalid, PlanValidationResult)
        """
        # Validate
        validation = self._validator.validate(
            nodes=nodes,
            dependencies=dependencies,
            constraints=constraints,
        )

        if not validation.valid:
            return None, validation

        # Get current plan
        from sqlalchemy import select
        stmt = select(PlanORM).where(PlanORM.id == plan_id)
        result = await self._session.execute(stmt)
        plan_orm = result.scalar_one_or_none()

        if not plan_orm:
            validation.errors.append(f"Plan '{plan_id}' not found.")
            validation.valid = False
            return None, validation

        new_version = plan_orm.current_version + 1
        graph = validation.graph
        graph_hash = graph.compute_hash() if graph else ""

        version_orm = PlanVersionORM(
            id=new_id(IdPrefix.PLAN_VERSION),
            plan_id=plan_id,
            version=new_version,
            graph_hash=graph_hash,
            reason=reason,
        )
        self._session.add(version_orm)
        await self._session.flush()

        # Persist nodes and dependencies
        for node in nodes:
            node_orm = PlanNodeORM(
                id=new_id(IdPrefix.PLAN_NODE),
                plan_version_id=version_orm.id,
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

        for dep in dependencies:
            dep_orm = PlanDependencyORM(
                id=new_id(IdPrefix.PLAN_DEPENDENCY),
                plan_version_id=version_orm.id,
                source_node_key=dep.source_node_key,
                target_node_key=dep.target_node_key,
                dependency_type=dep.dependency_type,
                condition=dep.condition,
            )
            self._session.add(dep_orm)

        # Mark previous version as superseded
        plan_orm.current_version = new_version
        plan_orm.status = PlanStatus.VALID.value
        await self._session.flush()

        logger.info(
            "plan_version_superseded",
            plan_id=plan_id,
            old_version=new_version - 1,
            new_version=new_version,
            reason=reason,
        )

        return version_orm, validation

    # ------------------------------------------------------------------
    # Default Plan Generation
    # ------------------------------------------------------------------

    def _generate_default_plan(
        self, request: PlanRequest,
    ) -> tuple[list[PlanNode], list[PlanDependency]]:
        """Generate a minimal default plan when no nodes are provided.

        Creates a single AGENT_TASK node followed by a VERIFICATION node.
        The agent handles internal decomposition through its own workflow.

        For multi-node model-assisted planning, the LLM integration
        will be wired in C5.4 v2 via the ModelGateway.
        """
        agent_slug = (
            request.preferred_agents[0]
            if request.preferred_agents
            else None
        )

        task_node = PlanNode(
            node_key="main_task",
            name="Execute Objective",
            description=request.objective,
            node_type="AGENT_TASK",
            agent_slug=agent_slug,
            required_capabilities=[],
            depends_on=[],
        )

        verify_node = PlanNode(
            node_key="verify_output",
            name="Verify Output",
            description="Verify the task output meets requirements.",
            node_type="VERIFICATION",
            depends_on=["main_task"],
        )

        dependency = PlanDependency(
            source_node_key="main_task",
            target_node_key="verify_output",
            dependency_type="HARD",
        )

        return [task_node, verify_node], [dependency]

    # ------------------------------------------------------------------
    # Plan Repair
    # ------------------------------------------------------------------

    def _attempt_repair(
        self,
        request: PlanRequest,
        original_nodes: list[PlanNode],
        original_deps: list[PlanDependency],
        validation: PlanValidationResult,
    ) -> tuple[list[PlanNode], list[PlanDependency]]:
        """Attempt to fix a plan based on validation errors.

        C5.4 v1: Simple heuristic repair. Removes invalid nodes/edges.
        C5.4 v2: Model-assisted repair using build_repair_prompt().
        """
        nodes = list(original_nodes)
        deps = list(original_deps)

        # Remove nodes with unregistered capabilities
        if self._validator._capabilities:
            valid_nodes: list[PlanNode] = []
            removed_keys: set[str] = set()

            for node in nodes:
                missing = [
                    c for c in node.required_capabilities
                    if c not in self._validator._capabilities
                ]
                if missing and node.node_type == "AGENT_TASK":
                    # Strip missing capabilities rather than removing the node
                    node.required_capabilities = [
                        c for c in node.required_capabilities
                        if c in self._validator._capabilities
                    ]
                    logger.warning(
                        "plan_repair_stripped_capabilities",
                        node=node.node_key,
                        removed=missing,
                    )
                valid_nodes.append(node)

            nodes = valid_nodes

        # Remove duplicate dependencies
        seen: set[tuple[str, str]] = set()
        unique_deps: list[PlanDependency] = []
        for dep in deps:
            key = (dep.source_node_key, dep.target_node_key)
            if key not in seen:
                seen.add(key)
                unique_deps.append(dep)
        deps = unique_deps

        return nodes, deps