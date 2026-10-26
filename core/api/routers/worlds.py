"""
World REST API (C7 §47 analog).

Endpoints for world instance management, state, snapshots,
health, and observation.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.api.dependencies.database import get_session
from core.api.dependencies.security import require_active_organization
from core.security.context import SecurityContext
from core.storage.models.world import WorldInstanceORM, WorldORM, WorldVersionORM
from core.storage.models.world_state import (
    WorldComponentORM,
    WorldHealthRecordORM,
    WorldSnapshotORM,
    WorldStateVersionORM,
)
from core.worlds.manager.manager import WorldManager
from core.worlds.state.snapshots import WorldSnapshotManager
from core.worlds.state.state_manager import WorldStateManager


router = APIRouter(prefix="/api/v1/worlds", tags=["worlds"])


# ------------------------------------------------------------------
# World Registry
# ------------------------------------------------------------------


@router.get("")
async def list_worlds(
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all registered worlds."""
    stmt = select(WorldORM).order_by(WorldORM.slug.asc())
    result = await session.execute(stmt)
    worlds = list(result.scalars().all())

    return {
        "worlds": [
            {
                "id": w.id,
                "slug": w.slug,
                "name": w.name,
                "publisher": w.publisher,
                "latest_version": w.latest_version,
            }
            for w in worlds
        ],
        "total": len(worlds),
    }


@router.get("/{world_slug}/versions")
async def list_world_versions(
    world_slug: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List versions of a world."""
    world_stmt = select(WorldORM).where(WorldORM.slug == world_slug)
    world_result = await session.execute(world_stmt)
    world = world_result.scalar_one_or_none()

    if not world:
        return {"error": f"World '{world_slug}' not found."}

    stmt = (
        select(WorldVersionORM)
        .where(WorldVersionORM.world_id == world.id)
        .order_by(WorldVersionORM.version.desc())
    )
    result = await session.execute(stmt)
    versions = list(result.scalars().all())

    return {
        "world_slug": world_slug,
        "versions": [
            {"id": v.id, "version": v.version}
            for v in versions
        ],
    }


# ------------------------------------------------------------------
# World Instances
# ------------------------------------------------------------------


@router.get("/instances/{instance_id}")
async def get_world_instance(
    instance_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a world instance by ID."""
    stmt = select(WorldInstanceORM).where(
        WorldInstanceORM.id == instance_id,
        WorldInstanceORM.organization_id == ctx.active_organization_id,
    )
    result = await session.execute(stmt)
    instance = result.scalar_one_or_none()

    if not instance:
        return {"error": "World instance not found."}

    return {
        "id": instance.id,
        "world_version_id": instance.world_version_id,
        "status": instance.status,
        "clock_mode": instance.clock_mode,
        "resource_profile": instance.resource_profile,
        "started_at": instance.started_at.isoformat() if instance.started_at else None,
    }


@router.post("/instances/{instance_id}/start")
async def start_world(
    instance_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Start a provisioned world instance."""
    mgr = WorldManager(session)
    instance = await mgr.start(instance_id)
    return {"id": instance.id, "status": instance.status}


@router.post("/instances/{instance_id}/pause")
async def pause_world(
    instance_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Pause a running world instance."""
    mgr = WorldManager(session)
    instance = await mgr.pause(instance_id)
    return {"id": instance.id, "status": instance.status}


@router.post("/instances/{instance_id}/resume")
async def resume_world(
    instance_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Resume a paused world instance."""
    mgr = WorldManager(session)
    instance = await mgr.resume(instance_id)
    return {"id": instance.id, "status": instance.status}


@router.post("/instances/{instance_id}/reset")
async def reset_world(
    instance_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Reset a world instance to its base state."""
    mgr = WorldManager(session)
    instance = await mgr.reset(instance_id)
    return {"id": instance.id, "status": instance.status}


@router.delete("/instances/{instance_id}")
async def destroy_world(
    instance_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Destroy a world instance."""
    mgr = WorldManager(session)
    success = await mgr.destroy(instance_id)
    return {"destroyed": success}


# ------------------------------------------------------------------
# World State
# ------------------------------------------------------------------


@router.get("/instances/{instance_id}/state")
async def get_world_state(
    instance_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get the current state of a world instance."""
    state_mgr = WorldStateManager(session)
    current = await state_mgr.get_current_state(instance_id)

    if not current:
        return {"version": 0, "state": {}}

    return {
        "version": current.version,
        "filesystem": current.filesystem_state,
        "database": current.database_state,
        "browser": current.browser_state,
        "application": current.application_state,
        "environment": current.environment_variables,
        "network": current.network_state,
    }


@router.get("/instances/{instance_id}/state/history")
async def get_state_history(
    instance_id: str,
    limit: int = 20,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get the state version history."""
    state_mgr = WorldStateManager(session)
    history = await state_mgr.get_state_history(instance_id, limit=limit)

    return {
        "instance_id": instance_id,
        "versions": [
            {
                "version": v.version,
                "triggered_by": v.triggered_by,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in history
        ],
        "total": len(history),
    }


# ------------------------------------------------------------------
# World Snapshots
# ------------------------------------------------------------------


@router.post("/instances/{instance_id}/snapshots")
async def create_snapshot(
    instance_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a snapshot of the world state."""
    snap_mgr = WorldSnapshotManager(session)
    snapshot = await snap_mgr.create_snapshot(instance_id)

    return {
        "snapshot_id": snapshot.id,
        "snapshot_type": snapshot.snapshot_type,
        "state_hash": snapshot.state_hash,
    }


@router.get("/instances/{instance_id}/snapshots")
async def list_snapshots(
    instance_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List snapshots for a world instance."""
    snap_mgr = WorldSnapshotManager(session)
    snapshots = await snap_mgr.list_snapshots(instance_id)

    return {
        "instance_id": instance_id,
        "snapshots": [
            {
                "id": s.id,
                "type": s.snapshot_type,
                "state_hash": s.state_hash,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in snapshots
        ],
        "total": len(snapshots),
    }


# ------------------------------------------------------------------
# World Health
# ------------------------------------------------------------------


@router.get("/instances/{instance_id}/health")
async def get_world_health(
    instance_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get the health status of a world instance."""
    mgr = WorldManager(session)
    health = await mgr.health(instance_id)

    return {
        "world_id": health.world_id,
        "status": health.status.value,
        "components": health.components,
        "cpu_usage": health.cpu_usage,
        "memory_usage_mb": health.memory_usage_mb,
        "network_status": health.network_status,
        "last_heartbeat": health.last_heartbeat.isoformat() if health.last_heartbeat else None,
    }


# ------------------------------------------------------------------
# World Observation
# ------------------------------------------------------------------


@router.get("/instances/{instance_id}/observe")
async def observe_world(
    instance_id: str,
    ctx: SecurityContext = Depends(require_active_organization),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a point-in-time observation of the world."""
    mgr = WorldManager(session)
    obs = await mgr.observe(instance_id)

    return {
        "world_id": obs.world_id,
        "timestamp": obs.timestamp.isoformat(),
        "state": obs.state,
        "artifacts": obs.artifacts,
        "events": obs.events,
    }