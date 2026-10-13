"""
Shared State Store (C5 §19-22).

Manages the shared orchestration state for a single execution.
Provides versioned reads, validated patch application, and
optimistic concurrency control.

Architecture:
    Agent → sdk.orchestration.update_state(patch)
        ↓
    SharedStateStore.apply_patch()
        ↓
    1. Validate patch (StatePatchValidator)
    2. Check concurrency (OptimisticConcurrencyControl)
    3. Apply patch to state
    4. Increment version
    5. Persist patch record (StatePatchORM)
    6. Persist updated state (SharedStateORM)
    7. Emit STATE_PATCH_APPLIED event

Invariants enforced:
  - Invariant 5: Execution history is append-only (patches never deleted)
  - Invariant 6: State changes are versioned (every patch increments version)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import EventType, StatePatchOperation
from schemas.domain.orchestration import StatePatch

from core.api.errors.exceptions import ConflictError, NotFoundError, ValidationError
from core.kernel.kernel import ExecutionKernel
from core.observability.logging import get_logger
from core.orchestration.state.concurrency import (
    ConcurrencyConflict,
    OptimisticConcurrencyControl,
)
from core.orchestration.state.patches import (
    PatchApplicationError,
    StatePatchValidator,
)
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.orchestration_state import (
    SharedStateORM,
    StatePatchORM,
)


logger = get_logger("dsrt.orchestration.state")


class SharedStateStore:
    """Manages versioned shared state for orchestration executions.

    Usage:
        store = SharedStateStore(session, kernel)
        state = await store.get_state(orchestration_execution_id)
        new_version = await store.apply_patch(
            orchestration_execution_id,
            patch=StatePatch(path="/findings", operation="add", value=[...]),
            source="research_agent",
        )
    """

    def __init__(
        self,
        session: AsyncSession,
        kernel: ExecutionKernel | None = None,
    ) -> None:
        self._session = session
        self._kernel = kernel
        self._occ = OptimisticConcurrencyControl()

    async def get_or_create_state(
        self,
        orchestration_execution_id: str,
    ) -> SharedStateORM:
        """Get the shared state for an execution, creating it if needed."""
        stmt = (
            select(SharedStateORM)
            .where(
                SharedStateORM.orchestration_execution_id
                == orchestration_execution_id
            )
        )
        result = await self._session.execute(stmt)
        state = result.scalar_one_or_none()

        if state is None:
            state = SharedStateORM(
                id=new_id(IdPrefix.SHARED_STATE),
                orchestration_execution_id=orchestration_execution_id,
                version=1,
                data={},
            )
            self._session.add(state)
            await self._session.flush()
            logger.info(
                "shared_state_created",
                execution_id=orchestration_execution_id,
                state_id=state.id,
            )

        return state

    async def get_state(
        self,
        orchestration_execution_id: str,
    ) -> dict[str, Any]:
        """Get the current shared state data."""
        state = await self.get_or_create_state(orchestration_execution_id)
        return dict(state.data)

    async def get_state_version(
        self,
        orchestration_execution_id: str,
    ) -> int:
        """Get the current state version number."""
        state = await self.get_or_create_state(orchestration_execution_id)
        return state.version

    async def read_value(
        self,
        orchestration_execution_id: str,
        path: str,
    ) -> Any:
        """Read a specific value from the shared state using JSON Pointer."""
        state_data = await self.get_state(orchestration_execution_id)
        return StatePatchValidator.get_value(state_data, path)

    async def apply_patch(
        self,
        orchestration_execution_id: str,
        patch: StatePatch,
        *,
        source: str | None = None,
    ) -> int:
        """Apply a validated patch to the shared state.

        Pipeline (C5 §21-23):
          1. Validate patch schema
          2. Load current state
          3. Check optimistic concurrency (if expected_version provided)
          4. Apply patch to state data
          5. Increment version
          6. Persist patch record (append-only)
          7. Persist updated state
          8. Emit event

        Returns:
            The new state version number.

        Raises:
            ValidationError: If the patch is invalid.
            ConflictError: If there's a concurrency conflict.
            NotFoundError: If the execution doesn't exist.
        """
        patch_source = source or patch.source

        # 1. Validate patch
        try:
            StatePatchValidator.validate_path(patch.path)
            StatePatchValidator.validate_operation(patch.operation)
        except PatchApplicationError as e:
            raise ValidationError(str(e)) from e

        # 2. Load current state
        state_orm = await self.get_or_create_state(orchestration_execution_id)
        current_version = state_orm.version
        current_data = dict(state_orm.data)

        # 3. Optimistic concurrency check (C5 §23)
        if patch.expected_version is not None:
            try:
                self._occ.check_version(
                    expected_version=patch.expected_version,
                    actual_version=current_version,
                    patch_source=patch_source,
                    patch_path=patch.path,
                )
            except ConcurrencyConflict as conflict:
                logger.warning(
                    "state_concurrency_conflict",
                    execution_id=orchestration_execution_id,
                    expected=conflict.expected_version,
                    actual=conflict.actual_version,
                    source=patch_source,
                    path=patch.path,
                )

                # Emit conflict event
                await self._emit_event(
                    orchestration_execution_id,
                    EventType.AGENT_EVENT,
                    {
                        "state_event": "STATE_CONFLICT_DETECTED",
                        "expected_version": conflict.expected_version,
                        "actual_version": conflict.actual_version,
                        "source": patch_source,
                        "path": patch.path,
                    },
                )

                raise ConflictError(
                    conflict.message,
                    metadata={
                        "expected_version": conflict.expected_version,
                        "actual_version": conflict.actual_version,
                        "source": patch_source,
                        "path": patch.path,
                    },
                ) from conflict

        # 4. Apply patch
        try:
            new_data = StatePatchValidator.apply_patch(
                current_data,
                patch.path,
                patch.operation,
                patch.value,
            )
        except PatchApplicationError as e:
            raise ValidationError(str(e)) from e

        # 5. Increment version
        new_version = current_version + 1

        # 6. Persist patch record (append-only, Invariant 5)
        patch_orm = StatePatchORM(
            id=new_id(IdPrefix.STATE_PATCH),
            shared_state_id=state_orm.id,
            orchestration_execution_id=orchestration_execution_id,
            path=patch.path,
            operation=patch.operation,
            value=patch.value,
            source=patch_source,
            reason=patch.reason,
            previous_version=current_version,
            new_version=new_version,
        )
        self._session.add(patch_orm)

        # 7. Persist updated state
        state_orm.data = new_data
        state_orm.version = new_version
        await self._session.flush()

        # 8. Emit event
        await self._emit_event(
            orchestration_execution_id,
            EventType.AGENT_EVENT,
            {
                "state_event": "STATE_PATCH_APPLIED",
                "patch_id": patch_orm.id,
                "path": patch.path,
                "operation": patch.operation,
                "source": patch_source,
                "previous_version": current_version,
                "new_version": new_version,
            },
        )

        logger.info(
            "state_patch_applied",
            execution_id=orchestration_execution_id,
            patch_id=patch_orm.id,
            path=patch.path,
            operation=patch.operation,
            source=patch_source,
            version=f"{current_version} -> {new_version}",
        )

        return new_version

    async def apply_patches(
        self,
        orchestration_execution_id: str,
        patches: list[StatePatch],
        *,
        source: str | None = None,
    ) -> int:
        """Apply multiple patches atomically.

        All patches are applied sequentially within the same version
        increment. If any patch fails, none are applied.

        Returns:
            The new state version number.
        """
        if not patches:
            return await self.get_state_version(orchestration_execution_id)

        # Validate all patches first
        for i, patch in enumerate(patches):
            try:
                StatePatchValidator.validate_path(patch.path)
                StatePatchValidator.validate_operation(patch.operation)
            except PatchApplicationError as e:
                raise ValidationError(
                    f"Patch {i} invalid: {e}"
                ) from e

        # Load state
        state_orm = await self.get_or_create_state(orchestration_execution_id)
        current_version = state_orm.version
        current_data = dict(state_orm.data)

        # Apply all patches to the data
        try:
            new_data = StatePatchValidator.apply_patches(
                current_data,
                [
                    {
                        "path": p.path,
                        "operation": p.operation,
                        "value": p.value,
                    }
                    for p in patches
                ],
            )
        except PatchApplicationError as e:
            raise ValidationError(str(e)) from e

        new_version = current_version + 1
        patch_source = source or "batch"

        # Persist each patch record
        for patch in patches:
            patch_orm = StatePatchORM(
                id=new_id(IdPrefix.STATE_PATCH),
                shared_state_id=state_orm.id,
                orchestration_execution_id=orchestration_execution_id,
                path=patch.path,
                operation=patch.operation,
                value=patch.value,
                source=patch.source,
                reason=patch.reason,
                previous_version=current_version,
                new_version=new_version,
            )
            self._session.add(patch_orm)

        # Update state
        state_orm.data = new_data
        state_orm.version = new_version
        await self._session.flush()

        logger.info(
            "state_patches_applied_batch",
            execution_id=orchestration_execution_id,
            patch_count=len(patches),
            version=f"{current_version} -> {new_version}",
        )

        return new_version

    async def get_patch_history(
        self,
        orchestration_execution_id: str,
        limit: int = 100,
    ) -> list[StatePatchORM]:
        """Get the patch history for an execution (append-only, Invariant 5)."""
        state_orm = await self.get_or_create_state(orchestration_execution_id)

        stmt = (
            select(StatePatchORM)
            .where(StatePatchORM.shared_state_id == state_orm.id)
            .order_by(StatePatchORM.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _emit_event(
        self,
        execution_id: str,
        event_type: EventType,
        payload: dict[str, Any],
    ) -> None:
        """Emit a state event into the execution trajectory."""
        if not self._kernel:
            return
        try:
            await self._kernel.emit_event(
                execution_id=execution_id,
                event_type=event_type,
                source="dsrt.orchestration.state",
                payload=payload,
            )
        except Exception as e:
            logger.warning(
                "state_event_emission_failed",
                execution_id=execution_id,
                error=str(e),
            )