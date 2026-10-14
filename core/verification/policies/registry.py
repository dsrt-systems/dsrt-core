"""
Policy Registry (C6 §10, §48).

Database-backed policy storage for organization-specific
verification policies.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.verification import (
    VerificationPolicy,
    VerificationThresholds,
)

from core.observability.logging import get_logger
from core.storage.models.verification import VerificationPolicyORM


logger = get_logger("dsrt.verification.registry")


class PolicyRegistry:
    """Database-backed verification policy registry.

    Usage:
        registry = PolicyRegistry(session)
        await registry.save(policy)
        loaded = await registry.load("research_v1")
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(
        self,
        policy: VerificationPolicy,
        organization_id: str | None = None,
    ) -> VerificationPolicyORM:
        """Save or update a verification policy."""
        # Check if exists
        existing = await self.load_orm(policy.id)

        if existing:
            existing.version = policy.version
            existing.name = policy.name
            existing.description = policy.description
            existing.required_checks = policy.required_checks
            existing.optional_checks = policy.optional_checks
            existing.thresholds = policy.thresholds.model_dump()
            existing.failure_actions = {
                k: v.model_dump() for k, v in policy.failure_actions.items()
            }
            existing.risk_level = policy.risk_level
            existing.deterministic_must_pass = policy.deterministic_must_pass
            existing.metadata_json = policy.metadata
            await self._session.flush()
            logger.info("policy_updated", policy_id=policy.id)
            return existing

        orm = VerificationPolicyORM(
            id=policy.id,
            version=policy.version,
            name=policy.name,
            description=policy.description,
            organization_id=organization_id,
            required_checks=policy.required_checks,
            optional_checks=policy.optional_checks,
            thresholds=policy.thresholds.model_dump(),
            failure_actions={
                k: v.model_dump() for k, v in policy.failure_actions.items()
            },
            risk_level=policy.risk_level,
            deterministic_must_pass=policy.deterministic_must_pass,
            metadata_json=policy.metadata,
        )
        self._session.add(orm)
        await self._session.flush()

        logger.info("policy_saved", policy_id=policy.id)
        return orm

    async def load(self, policy_id: str) -> VerificationPolicy | None:
        """Load a verification policy as a domain schema."""
        orm = await self.load_orm(policy_id)
        if not orm:
            return None

        return VerificationPolicy(
            id=orm.id,
            version=orm.version,
            name=orm.name,
            description=orm.description,
            required_checks=orm.required_checks or [],
            optional_checks=orm.optional_checks or [],
            thresholds=VerificationThresholds(**(orm.thresholds or {})),
            failure_actions=orm.failure_actions or {},
            risk_level=orm.risk_level,
            deterministic_must_pass=orm.deterministic_must_pass,
            metadata=orm.metadata_json or {},
        )

    async def load_orm(
        self, policy_id: str,
    ) -> VerificationPolicyORM | None:
        """Load a policy ORM record."""
        stmt = select(VerificationPolicyORM).where(
            VerificationPolicyORM.id == policy_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_policies(
        self,
        organization_id: str | None = None,
    ) -> list[VerificationPolicy]:
        """List all policies, optionally filtered by organization."""
        stmt = select(VerificationPolicyORM)
        if organization_id:
            stmt = stmt.where(
                VerificationPolicyORM.organization_id == organization_id,
            )
        stmt = stmt.order_by(VerificationPolicyORM.id.asc())
        result = await self._session.execute(stmt)
        orms = list(result.scalars().all())

        policies = []
        for orm in orms:
            policies.append(VerificationPolicy(
                id=orm.id,
                version=orm.version,
                name=orm.name,
                description=orm.description,
                required_checks=orm.required_checks or [],
                optional_checks=orm.optional_checks or [],
                thresholds=VerificationThresholds(**(orm.thresholds or {})),
                failure_actions=orm.failure_actions or {},
                risk_level=orm.risk_level,
                deterministic_must_pass=orm.deterministic_must_pass,
                metadata=orm.metadata_json or {},
            ))
        return policies

    async def delete(self, policy_id: str) -> bool:
        """Delete a verification policy."""
        orm = await self.load_orm(policy_id)
        if not orm:
            return False
        await self._session.delete(orm)
        await self._session.flush()
        logger.info("policy_deleted", policy_id=policy_id)
        return True