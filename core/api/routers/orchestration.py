"""
Orchestration REST API (C5 §58).

Endpoints for plan management, orchestration execution control,
shared state, checkpoints, and replanning.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.agents.registry import AgentRegistry
from core.api.dependencies import get_security_context
from core.kernel.kernel import ExecutionKernel
from core.orchestration.checkpoints.checkpoint import CheckpointManager
from core.orchestration.planner.planner import Planner
from core.orchestration.planner.validator import PlanValidator
from core.orchestration.replanning.replanner import ReplanRequest, Replanner
from core.orchestration.state.state_store import SharedStateStore
from core.repositories import (
    AgentRepository,
    CapabilityRepository,
    EventRepository,
    ExecutionRepository,
    TaskRepository,
)
from core.security.context import SecurityContext
from core.storage.database import get_db_session
from core.storage.models.orchestration import (
    NodeExecutionORM,
    OrchestrationExecutionORM,
    PlanORM,
    PlanVersionORM,
)
from schemas.api.orchestration import (
    ApplyStatePatchRequest,
    CreatePlanRequest,
    ReplanRequest as ReplanRequestSchema,
)
from schemas.domain.orchestration import PlanConstraints


router = APIRouter(prefix="/api/v1", tags=["orchestration"])


def _require_active_org(ctx: SecurityContext = Depends(get_security_context)) -> SecurityContext:
    """Ensure caller has an active organization context."""
    org_id = getattr(ctx, "active_organization_id", None)
    if not org_id:
        from core.api.errors.exceptions import ForbiddenError

        raise ForbiddenError("Active organization is required.")
    return ctx


def _get_kernel(session: AsyncSession) -> ExecutionKernel:
    task_repo = TaskRepository(session)
    exe_repo = ExecutionRepository(session)
    agent_repo = AgentRepository(session)
    cap_repo = CapabilityRepository(session)
    event_repo = EventRepository(session)
    return ExecutionKernel(
        task_repo,
        exe_repo,
        AgentRegistry(agent_repo, cap_repo),
        event_repo,
    )


@router.post("/tasks/{task_id}/plans", status_code=201)
async def create_plan(
    task_id: str,
    body: CreatePlanRequest,
    ctx: SecurityContext = Depends(_require_active_org),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Create a new plan for a task."""
    kernel = _get_kernel(session)
    planner = Planner(session, kernel)

    from schemas.domain.orchestration import PlanRequest

    request = PlanRequest(
        task_id=task_id,
        objective=body.objective,
        constraints=body.constraints,
        preferred_agents=body.preferred_agents,
        nodes=body.nodes,
        dependencies=body.dependencies,
        metadata=body.metadata,
    )

    plan_orm, version_orm, validation = await planner.create_plan(
        request=request,
        organization_id=ctx.active_organization_id,
    )

    return {
        "plan_id": plan_orm.id,
        "version_id": version_orm.id,
        "version": version_orm.version,
        "status": plan_orm.status,
        "valid": validation.valid,
        "errors": validation.errors,
        "warnings": validation.warnings,
    }


@router.get("/tasks/{task_id}/plans")
async def list_plans(
    task_id: str,
    ctx: SecurityContext = Depends(_require_active_org),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """List all plans for a task."""
    stmt = (
        select(PlanORM)
        .where(
            PlanORM.task_id == task_id,
            PlanORM.organization_id == ctx.active_organization_id,
        )
        .order_by(PlanORM.created_at.desc())
    )
    result = await session.execute(stmt)
    plans = list(result.scalars().all())

    return {
        "plans": [
            {
                "id": p.id,
                "task_id": p.task_id,
                "current_version": p.current_version,
                "status": p.status,
                "objective": p.objective,
            }
            for p in plans
        ],
        "total": len(plans),
    }


@router.post("/plans/{plan_id}/validate")
async def validate_plan(
    plan_id: str,
    ctx: SecurityContext = Depends(_require_active_org),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Validate the latest version of a plan."""
    stmt = (
        select(PlanVersionORM)
        .where(PlanVersionORM.plan_id == plan_id)
        .order_by(PlanVersionORM.version.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    version = result.scalar_one_or_none()

    if not version:
        return {"valid": False, "errors": ["Plan version not found."], "warnings": []}

    planner = Planner(session)
    nodes = await planner._load_plan_nodes(version.id)
    deps = await planner._load_plan_dependencies(version.id)

    validator = PlanValidator()
    validation = validator.validate(nodes, deps, PlanConstraints())

    return {
        "valid": validation.valid,
        "errors": validation.errors,
        "warnings": validation.warnings,
    }


@router.get("/orchestration/{execution_id}")
async def get_orchestration(
    execution_id: str,
    ctx: SecurityContext = Depends(_require_active_org),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Get orchestration execution details."""
    stmt = select(OrchestrationExecutionORM).where(
        OrchestrationExecutionORM.id == execution_id,
        OrchestrationExecutionORM.organization_id == ctx.active_organization_id,
    )
    result = await session.execute(stmt)
    exe = result.scalar_one_or_none()

    if not exe:
        return {"error": "Orchestration execution not found."}

    return {
        "id": exe.id,
        "task_id": exe.task_id,
        "plan_id": exe.plan_id,
        "plan_version_id": exe.plan_version_id,
        "status": exe.status,
        "active_nodes": exe.active_nodes,
        "completed_nodes": exe.completed_nodes,
        "failed_nodes": exe.failed_nodes,
        "started_at": exe.started_at.isoformat() if exe.started_at else None,
        "completed_at": exe.completed_at.isoformat() if exe.completed_at else None,
    }


@router.post("/orchestration/{execution_id}/pause")
async def pause_orchestration(
    execution_id: str,
    ctx: SecurityContext = Depends(_require_active_org),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Pause an orchestration execution."""
    stmt = select(OrchestrationExecutionORM).where(
        OrchestrationExecutionORM.id == execution_id,
        OrchestrationExecutionORM.organization_id == ctx.active_organization_id,
    )
    result = await session.execute(stmt)
    exe = result.scalar_one_or_none()

    if not exe:
        return {"error": "Not found."}

    from schemas.domain.enums import OrchestrationStatus

    if exe.status == OrchestrationStatus.RUNNING.value:
        exe.status = OrchestrationStatus.PAUSED.value
        await session.flush()

    return {"id": exe.id, "status": exe.status}


@router.post("/orchestration/{execution_id}/resume")
async def resume_orchestration(
    execution_id: str,
    ctx: SecurityContext = Depends(_require_active_org),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Resume a paused orchestration execution."""
    stmt = select(OrchestrationExecutionORM).where(
        OrchestrationExecutionORM.id == execution_id,
        OrchestrationExecutionORM.organization_id == ctx.active_organization_id,
    )
    result = await session.execute(stmt)
    exe = result.scalar_one_or_none()

    if not exe:
        return {"error": "Not found."}

    from schemas.domain.enums import OrchestrationStatus

    if exe.status == OrchestrationStatus.PAUSED.value:
        exe.status = OrchestrationStatus.RUNNING.value
        await session.flush()

    return {"id": exe.id, "status": exe.status}


@router.post("/orchestration/{execution_id}/cancel")
async def cancel_orchestration(
    execution_id: str,
    ctx: SecurityContext = Depends(_require_active_org),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Cancel an orchestration execution."""
    stmt = select(OrchestrationExecutionORM).where(
        OrchestrationExecutionORM.id == execution_id,
        OrchestrationExecutionORM.organization_id == ctx.active_organization_id,
    )
    result = await session.execute(stmt)
    exe = result.scalar_one_or_none()

    if not exe:
        return {"error": "Not found."}

    from schemas.domain.enums import OrchestrationStatus

    exe.status = OrchestrationStatus.CANCELLED.value
    await session.flush()

    return {"id": exe.id, "status": exe.status}


@router.get("/orchestration/{execution_id}/nodes")
async def list_nodes(
    execution_id: str,
    ctx: SecurityContext = Depends(_require_active_org),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """List all node executions for an orchestration."""
    # Tenant scope via parent orchestration row
    parent_stmt = select(OrchestrationExecutionORM).where(
        OrchestrationExecutionORM.id == execution_id,
        OrchestrationExecutionORM.organization_id == ctx.active_organization_id,
    )
    parent = (await session.execute(parent_stmt)).scalar_one_or_none()
    if not parent:
        return {"nodes": [], "total": 0}

    stmt = (
        select(NodeExecutionORM)
        .where(NodeExecutionORM.orchestration_execution_id == execution_id)
        .order_by(NodeExecutionORM.created_at.asc())
    )
    result = await session.execute(stmt)
    nodes = list(result.scalars().all())

    return {
        "nodes": [
            {
                "id": n.id,
                "node_key": n.plan_node_key,
                "status": n.status,
                "attempt": n.attempt,
                "agent_slug": n.agent_slug,
                "error_code": n.error_code,
                "started_at": n.started_at.isoformat() if n.started_at else None,
                "completed_at": n.completed_at.isoformat() if n.completed_at else None,
            }
            for n in nodes
        ],
        "total": len(nodes),
    }


@router.get("/orchestration/{execution_id}/state")
async def get_state(
    execution_id: str,
    ctx: SecurityContext = Depends(_require_active_org),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Get the shared state for an orchestration execution."""
    store = SharedStateStore(session)
    state = await store.get_state(execution_id)
    version = await store.get_state_version(execution_id)
    return {"version": version, "data": state}


@router.post("/orchestration/{execution_id}/state/patches")
async def apply_patches(
    execution_id: str,
    body: ApplyStatePatchRequest,
    ctx: SecurityContext = Depends(_require_active_org),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Apply patches to the shared state."""
    store = SharedStateStore(session, _get_kernel(session))
    new_version = await store.apply_patches(
        execution_id,
        body.patches,
        source="api",
    )
    return {"version": new_version, "patches_applied": len(body.patches)}


@router.get("/orchestration/{execution_id}/checkpoints")
async def list_checkpoints(
    execution_id: str,
    ctx: SecurityContext = Depends(_require_active_org),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """List checkpoints for an orchestration execution."""
    mgr = CheckpointManager(session)
    checkpoints = await mgr.list_checkpoints(execution_id)
    return {
        "checkpoints": [
            {
                "id": c.id,
                "plan_version_id": c.plan_version_id,
                "node_states": c.node_states,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in checkpoints
        ],
        "total": len(checkpoints),
    }


@router.post("/orchestration/{execution_id}/replan")
async def replan(
    execution_id: str,
    body: ReplanRequestSchema,
    ctx: SecurityContext = Depends(_require_active_org),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Request replanning for an orchestration execution."""
    stmt = select(OrchestrationExecutionORM).where(
        OrchestrationExecutionORM.id == execution_id,
        OrchestrationExecutionORM.organization_id == ctx.active_organization_id,
    )
    result = await session.execute(stmt)
    exe = result.scalar_one_or_none()

    if not exe:
        return {"success": False, "errors": ["Execution not found."]}

    replanner = Replanner(session, _get_kernel(session))
    replan_result = await replanner.replan(
        ReplanRequest(
            orchestration_execution_id=execution_id,
            plan_id=exe.plan_id,
            current_plan_version_id=exe.plan_version_id,
            trigger="API_REQUEST",
            reason=body.reason,
            failed_node_keys=body.affected_nodes,
            replacement_nodes=body.new_nodes,
            replacement_dependencies=body.new_dependencies,
        )
    )

    return {
        "success": replan_result.success,
        "replan_id": replan_result.replan_id,
        "new_plan_version_id": replan_result.new_plan_version_id,
        "preserved_nodes": replan_result.preserved_node_keys,
        "affected_nodes": replan_result.affected_node_keys,
        "errors": replan_result.errors,
    }