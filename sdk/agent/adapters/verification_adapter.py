"""
VerificationSDK Implementation — C1 stub.

Full Verification Fabric arrives in C6. For C1, verification requests are
recorded as VerificationRun rows with status INCONCLUSIVE — this preserves
the event trail while making it clear no independent verification ran.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from core.observability.logging import get_logger
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models import VerificationRun
from core.storage.models.mixins import utcnow
from sdk.agent.interfaces.verification import SDKVerificationResult


logger = get_logger("sdk.verification")


class VerificationSDKImpl:
    """C1 stub — the full Verification Fabric arrives in Phase C6."""

    def __init__(
        self,
        session: AsyncSession,
        execution_id: str,
    ) -> None:
        self._session = session
        self._execution_id = execution_id

    async def verify(
        self,
        subject_id: str,
        policy_id: str,
        subject_type: str = "artifact",
    ) -> SDKVerificationResult:
        now = utcnow()
        run = VerificationRun(
            id=new_id(IdPrefix.VERIFICATION_RUN),
            execution_id=self._execution_id,
            subject_type=subject_type,
            subject_id=subject_id,
            policy_id=policy_id,
            status="INCONCLUSIVE",
            engine_version="c1-stub",
            started_at=now,
            completed_at=now,
        )
        self._session.add(run)
        await self._session.flush()

        logger.info(
            "verification_stub_recorded",
            verification_run_id=run.id,
            execution_id=self._execution_id,
            subject_type=subject_type,
            subject_id=subject_id,
            policy_id=policy_id,
        )

        return SDKVerificationResult(
            subject_id=subject_id,
            policy_id=policy_id,
            status="INCONCLUSIVE",
            summary=(
                "Verification is a C1 stub. Full independent verification ships in C6."
            ),
        )