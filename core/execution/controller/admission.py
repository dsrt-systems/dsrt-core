"""Execution admission gate validating configuration and budget thresholds."""

from typing import Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import BudgetDecision, ErrorCode
from schemas.domain.execution_c10 import ExecutionConfigurationCreate


class ExecutionAdmissionGate:
    """Validates execution admission against policies and pre-admission budget limits."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def evaluate_admission(
        self,
        config: ExecutionConfigurationCreate,
    ) -> Tuple[bool, BudgetDecision, str]:
        """Evaluates whether execution configuration is permitted to proceed."""
        if not config.organization_id:
            return False, BudgetDecision.HARD_BLOCK, ErrorCode.C10_MISSING_ORGANIZATION_ID.value

        if not config.model_identifier:
            return False, BudgetDecision.HARD_BLOCK, ErrorCode.C10_UNSUPPORTED_MODEL_IDENTIFIER.value

        if config.budget_limit_usd is not None and config.budget_limit_usd <= 0:
            return (
                False,
                BudgetDecision.HARD_BLOCK,
                ErrorCode.C10_BUDGET_EXCEEDED_PRE_ADMISSION.value,
            )

        return True, BudgetDecision.ALLOW, "Admission granted"