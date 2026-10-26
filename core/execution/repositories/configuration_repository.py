"""Execution configuration repository."""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.execution_c10 import ExecutionConfigurationORM
from schemas.domain.execution_c10 import ExecutionConfigurationCreate


class ExecutionConfigurationRepository:
    """Async repository for execution configurations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_configuration(
        self,
        config: ExecutionConfigurationCreate,
    ) -> ExecutionConfigurationORM:
        config_id = new_id(IdPrefix.C10_EXECUTION_CONFIGURATION)
        now = datetime.now(timezone.utc)

        amplification_str = [s.value if hasattr(s, "value") else str(s) for s in config.amplification_strategies]
        comp_mode_str = config.comparison_mode.value if hasattr(config.comparison_mode, "value") else (str(config.comparison_mode) if config.comparison_mode else None)

        orm = ExecutionConfigurationORM(
            id=config_id,
            organization_id=config.organization_id,
            protocol=config.protocol.value,
            mode=config.mode.value,
            model_identifier=config.model_identifier,
            model_provider=config.model_provider,
            system_prompt=config.system_prompt,
            parameters_json=config.parameters_json,
            amplification_strategies=amplification_str,
            comparison_mode=comp_mode_str,
            budget_limit_usd=config.budget_limit_usd,
            timeout_seconds=config.timeout_seconds,
            created_at=now,
            updated_at=now,
        )
        self.session.add(orm)
        await self.session.commit()
        await self.session.refresh(orm)
        return orm

    async def get_by_id(self, config_id: str) -> Optional[ExecutionConfigurationORM]:
        stmt = select(ExecutionConfigurationORM).where(ExecutionConfigurationORM.id == config_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()