"""
Benchmark Registry (C8 §5-7, §48-51).

Manages benchmark lifecycle: create, version, publish, discover.

Key principles:
  - Benchmarks are versioned and immutable once published (C8 §74)
  - Content hash ensures integrity (C8 §43)
  - Benchmark ≠ Experiment ≠ Run (C8 §5)
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.arena import Benchmark, BenchmarkConstraints
from schemas.domain.enums import BenchmarkType

from core.api.errors.exceptions import ConflictError, NotFoundError
from core.kernel.fingerprint import content_hash
from core.observability.logging import get_logger
from core.storage.models.arena import BenchmarkORM


logger = get_logger("dsrt.arena.benchmarks")


class BenchmarkRegistry:
    """Authoritative catalog for Arena benchmarks (C8 §5-7).

    Usage:
        registry = BenchmarkRegistry(session)
        benchmark = await registry.register(
            benchmark_id="research_v1",
            version="1.0.0",
            name="Research Benchmark",
            benchmark_type=BenchmarkType.WORKFLOW,
            metrics=["task_success", "evidence_quality"],
        )
        loaded = await registry.get("research_v1", "1.0.0")
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register(
        self,
        *,
        benchmark_id: str,
        version: str = "1.0.0",
        name: str = "",
        description: str = "",
        benchmark_type: BenchmarkType | str = BenchmarkType.CAPABILITY,
        task_suite_id: str | None = None,
        world_slug: str | None = None,
        world_version: str | None = None,
        metrics: list[str] | None = None,
        constraints: dict[str, Any] | None = None,
        organization_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> BenchmarkORM:
        """Register a new benchmark version (C8 §6).

        Idempotent per (benchmark_id, version) pair.
        """
        type_str = (
            benchmark_type.value
            if isinstance(benchmark_type, BenchmarkType)
            else benchmark_type
        )

        # Check for existing version
        existing = await self._get_orm(benchmark_id, version)
        if existing:
            raise ConflictError(
                f"Benchmark '{benchmark_id}' version '{version}' already exists."
            )

        # Compute content hash for integrity (C8 §74)
        hash_input = str({
            "id": benchmark_id,
            "version": version,
            "metrics": metrics or [],
            "constraints": constraints or {},
            "task_suite_id": task_suite_id,
        })
        c_hash = content_hash(hash_input)

        orm = BenchmarkORM(
            id=benchmark_id,
            version=version,
            name=name,
            description=description,
            benchmark_type=type_str,
            task_suite_id=task_suite_id,
            world_slug=world_slug,
            world_version=world_version,
            metrics=metrics or [],
            constraints=constraints or {},
            content_hash=c_hash,
            organization_id=organization_id,
            metadata_json=metadata or {},
        )
        self._session.add(orm)
        await self._session.flush()

        logger.info(
            "benchmark_registered",
            benchmark_id=benchmark_id,
            version=version,
            type=type_str,
            metrics_count=len(metrics or []),
        )

        return orm

    async def get(
        self,
        benchmark_id: str,
        version: str | None = None,
    ) -> Benchmark:
        """Get a benchmark as a domain schema."""
        orm = await self._get_orm(benchmark_id, version)
        if not orm:
            raise NotFoundError(
                f"Benchmark '{benchmark_id}'"
                + (f" version '{version}'" if version else "")
                + " not found."
            )
        return self._to_domain(orm)

    async def get_orm(
        self,
        benchmark_id: str,
        version: str | None = None,
    ) -> BenchmarkORM:
        """Get a benchmark ORM record."""
        orm = await self._get_orm(benchmark_id, version)
        if not orm:
            raise NotFoundError(f"Benchmark '{benchmark_id}' not found.")
        return orm

    async def list_benchmarks(
        self,
        benchmark_type: str | None = None,
        organization_id: str | None = None,
        limit: int = 50,
    ) -> list[Benchmark]:
        """List benchmarks with optional filters."""
        stmt = select(BenchmarkORM).order_by(BenchmarkORM.id.asc())

        if benchmark_type:
            stmt = stmt.where(BenchmarkORM.benchmark_type == benchmark_type)
        if organization_id:
            stmt = stmt.where(BenchmarkORM.organization_id == organization_id)

        stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return [self._to_domain(o) for o in result.scalars().all()]

    async def list_versions(
        self, benchmark_id: str,
    ) -> list[str]:
        """List all versions of a benchmark."""
        stmt = (
            select(BenchmarkORM.version)
            .where(BenchmarkORM.id == benchmark_id)
            .order_by(BenchmarkORM.version.desc())
        )
        result = await self._session.execute(stmt)
        return [row[0] for row in result.all()]

    async def verify_integrity(
        self, benchmark_id: str, version: str,
    ) -> bool:
        """Verify benchmark content hash matches (C8 §74)."""
        orm = await self._get_orm(benchmark_id, version)
        if not orm:
            return False

        expected_hash = content_hash(str({
            "id": orm.id,
            "version": orm.version,
            "metrics": orm.metrics,
            "constraints": orm.constraints,
            "task_suite_id": orm.task_suite_id,
        }))

        return orm.content_hash == expected_hash

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_orm(
        self, benchmark_id: str, version: str | None = None,
    ) -> BenchmarkORM | None:
        stmt = select(BenchmarkORM).where(BenchmarkORM.id == benchmark_id)
        if version:
            stmt = stmt.where(BenchmarkORM.version == version)
        else:
            stmt = stmt.order_by(BenchmarkORM.version.desc()).limit(1)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def _to_domain(orm: BenchmarkORM) -> Benchmark:
        return Benchmark(
            id=orm.id,
            version=orm.version,
            name=orm.name,
            description=orm.description,
            benchmark_type=BenchmarkType(orm.benchmark_type),
            task_suite_id=orm.task_suite_id,
            world_slug=orm.world_slug,
            world_version=orm.world_version,
            metrics=orm.metrics or [],
            constraints=BenchmarkConstraints(**(orm.constraints or {})),
            content_hash=orm.content_hash,
            metadata=orm.metadata_json or {},
        )