"""
Checkpoint Manager (C5 §28-29, §55, §70).

Manages durable checkpoints of orchestration execution state.
A checkpoint captures the complete graph state at a point in time,
enabling recovery after crashes or restarts.

Checkpoint Strategy (C5 §29):
  - After significant node completion
  - After major state mutation
  - Before risky external action
  - Before plan transition
  - Before long-running execution
  - On graceful shutdown

Checkpoints do NOT capture every token event — only meaningful
state transitions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import EventType, NodeStatus

from core.kernel.kernel import ExecutionKernel
from core.observability.logging import get_logger
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.orchestration import (
    NodeExecutionORM,
    OrchestrationCheckpointORM,
    OrchestrationExecutionORM,
)


logger = get_logger("dsrt.orchestration.checkpoints")


class CheckpointManager:
    """Creates and restores orchestration checkpoints.

    Usage:
        mgr = CheckpointManager(session, kernel)
        ckpt = await mgr.create_checkpoint(
            orchestration_execution_id="oex_...",
            plan_version_id="pnv_...",
        )
        # ... crash ...
        state = await mgr.restore_checkpoint(ckpt.id)
    """

    def __init__(
        self,
        session: AsyncSession,
        kernel: ExecutionKernel | None = None,
    ) -> None:
        self._session = session
        self._kernel = kernel

    async def create_checkpoint(
        self,
        orchestration_execution_id: str,
        plan_version_id: str,
        *,
        reason: str = "automatic",
    ) -> OrchestrationCheckpointORM:
        """Create a durable checkpoint of the current execution state.

        Captures:
          - Graph state (node statuses)
          - Active/completed/failed node lists
          - Resource usage snapshot
          - References to context and memory snapshots

        Returns:
            The persisted OrchestrationCheckpointORM.
        """
        # 1. Load current execution state
        exec_stmt = (
            select(OrchestrationExecutionORM)
            .where(OrchestrationExecutionORM.id == orchestration_execution_id)
        )
        exec_result = await self._session.execute(exec_stmt)
        execution = exec_result.scalar_one_or_none()

        if not execution:
            raise ValueError(
                f"Execution '{orchestration_execution_id}' not found."
            )

        # 2. Load all node executions for this orchestration
        node_stmt = (
            select(NodeExecutionORM)
            .where(
                NodeExecutionORM.orchestration_execution_id
                == orchestration_execution_id
            )
            .order_by(NodeExecutionORM.created_at.asc())
        )
        node_result = await self._session.execute(node_stmt)
        node_executions = list(node_result.scalars().all())

        # 3. Build node state map
        node_states: dict[str, str] = {}
        for ne in node_executions:
            # Use the latest status for each node key
            node_states[ne.plan_node_key] = ne.status

        # 4. Build graph state snapshot
        graph_state = {
            "total_nodes": len(node_states),
            "completed": [
                k for k, s in node_states.items()
                if s == NodeStatus.COMPLETED.value
            ],
            "failed": [
                k for k, s in node_states.items()
                if s == NodeStatus.FAILED.value
            ],
            "running": [
                k for k, s in node_states.items()
                if s == NodeStatus.RUNNING.value
            ],
            "pending": [
                k for k, s in node_states.items()
                if s in (
                    NodeStatus.PENDING.value,
                    NodeStatus.READY.value,
                    NodeStatus.QUEUED.value,
                )
            ],
            "blocked": [
                k for k, s in node_states.items()
                if s == NodeStatus.BLOCKED.value
            ],
        }

        # 5. Build resource state snapshot
        resource_state: dict[str, Any] = {}
        for ne in node_executions:
            if ne.resource_usage:
                resource_state[ne.plan_node_key] = ne.resource_usage

        # 6. Create checkpoint record
        checkpoint = OrchestrationCheckpointORM(
            id=new_id(IdPrefix.ORCHESTRATION_CHECKPOINT),
            orchestration_execution_id=orchestration_execution_id,
            plan_version_id=plan_version_id,
            graph_state=graph_state,
            node_states=node_states,
            resource_state=resource_state,
        )
        self._session.add(checkpoint)

        # 7. Update execution's checkpoint pointer
        execution.checkpoint_id = checkpoint.id
        await self._session.flush()

        # 8. Emit event
        await self._emit_event(
            orchestration_execution_id,
            EventType.AGENT_EVENT,
            {
                "checkpoint_event": "CHECKPOINT_CREATED",
                "checkpoint_id": checkpoint.id,
                "reason": reason,
                "completed_nodes": len(graph_state["completed"]),
                "running_nodes": len(graph_state["running"]),
                "pending_nodes": len(graph_state["pending"]),
            },
        )

        logger.info(
            "checkpoint_created",
            checkpoint_id=checkpoint.id,
            execution_id=orchestration_execution_id,
            reason=reason,
            completed=len(graph_state["completed"]),
            running=len(graph_state["running"]),
            pending=len(graph_state["pending"]),
        )

        return checkpoint

    async def restore_checkpoint(
        self,
        checkpoint_id: str,
    ) -> dict[str, Any]:
        """Restore execution state from a checkpoint.

        Returns the checkpoint's graph_state and node_states for the
        orchestrator to resume execution.

        The orchestrator is responsible for:
          1. Re-marking RUNNING nodes as PENDING (they were interrupted)
          2. Re-scheduling READY nodes
          3. Resuming from the checkpoint's plan version

        Returns:
            Dict with checkpoint data for the orchestrator.
        """
        stmt = (
            select(OrchestrationCheckpointORM)
            .where(OrchestrationCheckpointORM.id == checkpoint_id)
        )
        result = await self._session.execute(stmt)
        checkpoint = result.scalar_one_or_none()

        if not checkpoint:
            raise ValueError(f"Checkpoint '{checkpoint_id}' not found.")

        # Emit restore event
        await self._emit_event(
            checkpoint.orchestration_execution_id,
            EventType.AGENT_EVENT,
            {
                "checkpoint_event": "CHECKPOINT_RESTORED",
                "checkpoint_id": checkpoint_id,
                "plan_version_id": checkpoint.plan_version_id,
            },
        )

        logger.info(
            "checkpoint_restored",
            checkpoint_id=checkpoint_id,
            execution_id=checkpoint.orchestration_execution_id,
        )

        return {
            "checkpoint_id": checkpoint.id,
            "orchestration_execution_id": checkpoint.orchestration_execution_id,
            "plan_version_id": checkpoint.plan_version_id,
            "graph_state": checkpoint.graph_state,
            "node_states": checkpoint.node_states,
            "resource_state": checkpoint.resource_state,
            "created_at": checkpoint.created_at.isoformat()
            if checkpoint.created_at
            else None,
        }

    async def list_checkpoints(
        self,
        orchestration_execution_id: str,
        limit: int = 20,
    ) -> list[OrchestrationCheckpointORM]:
        """List checkpoints for an execution in reverse chronological order."""
        stmt = (
            select(OrchestrationCheckpointORM)
            .where(
                OrchestrationCheckpointORM.orchestration_execution_id
                == orchestration_execution_id
            )
            .order_by(OrchestrationCheckpointORM.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_checkpoint(
        self,
        orchestration_execution_id: str,
    ) -> OrchestrationCheckpointORM | None:
        """Get the most recent checkpoint for an execution."""
        checkpoints = await self.list_checkpoints(
            orchestration_execution_id, limit=1,
        )
        return checkpoints[0] if checkpoints else None

    def should_checkpoint(
        self,
        event: str,
        node_status: str | None = None,
        nodes_completed_since_last: int = 0,
    ) -> bool:
        """Determine if a checkpoint should be created (C5 §29).

        This is a heuristic — the orchestrator calls this after each
        significant event to decide whether to checkpoint.

        Args:
            event: The event that just occurred (e.g., 'NODE_COMPLETED').
            node_status: The new status of the affected node.
            nodes_completed_since_last: Count of completions since last checkpoint.

        Returns:
            True if a checkpoint should be created.
        """
        # After significant node completion (every 3 completions)
        if event == "NODE_COMPLETED" and nodes_completed_since_last >= 3:
            return True

        # After a node failure (for recovery)
        if event == "NODE_FAILED":
            return True

        # After replanning
        if event == "PLAN_REPLANNED":
            return True

        # Before risky actions (external, irreversible)
        if event == "RISKY_ACTION_PENDING":
            return True

        # On graceful shutdown
        if event == "SHUTDOWN_REQUESTED":
            return True

        # After plan transition
        if event == "PLAN_VERSION_CHANGED":
            return True

        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _emit_event(
        self,
        execution_id: str,
        event_type: EventType,
        payload: dict[str, Any],
    ) -> None:
        """Emit a checkpoint event into the execution trajectory."""
        if not self._kernel:
            return
        try:
            await self._kernel.emit_event(
                execution_id=execution_id,
                event_type=event_type,
                source="dsrt.orchestration.checkpoints",
                payload=payload,
            )
        except Exception as e:
            logger.warning(
                "checkpoint_event_emission_failed",
                execution_id=execution_id,
                error=str(e),
            )