"""
VerificationSDK Implementation (C6 §54).

Full C6 implementation replacing the C1 stub. Bridges the agent-facing
VerificationSDK Protocol to the Core VerificationEngine, EvidenceStore,
and ReviewManager.

Architecture:
    Agent → sdk.verification.verify(subject, policy)
        ↓
    VerificationSDKImpl
        ↓
    VerificationEngine.verify()
        ↓
    C6VerificationResult → SDKVerificationResult
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import VerificationStatus
from schemas.domain.verification import VerificationRequest

from core.kernel.kernel import ExecutionKernel
from core.observability.logging import get_logger
from core.verification.engine.engine import VerificationEngine
from core.verification.evidence.store import EvidenceStore
from sdk.agent.interfaces.verification import (
    SDKEvidenceResult,
    SDKVerificationResult,
)


logger = get_logger("sdk.verification")


class VerificationSDKImpl:
    """Full C6 VerificationSDK implementation.

    Replaces the C1 stub that recorded INCONCLUSIVE for all requests.
    Now delegates to the real VerificationEngine.
    """

    def __init__(
        self,
        session: AsyncSession,
        execution_id: str,
        kernel: ExecutionKernel | None = None,
        organization_id: str = "",
    ) -> None:
        self._session = session
        self._execution_id = execution_id
        self._kernel = kernel
        self._organization_id = organization_id

        # Lazy-initialized services
        self._engine: VerificationEngine | None = None
        self._evidence_store: EvidenceStore | None = None

    def _get_engine(self) -> VerificationEngine:
        if self._engine is None:
            # VerificationEngine requires keyword-only execution_id + organization_id
            # (bound at construction; never taken from agent-controllable request metadata).
            org_id = self._organization_id
            if not org_id and self._kernel is not None:
                org_id = getattr(self._kernel, "organization_id", "") or ""
            if not org_id:
                org_id = "org_default"

            self._engine = VerificationEngine(
                self._session,
                self._kernel,
                execution_id=self._execution_id,
                organization_id=org_id,
            )
        return self._engine

    def _get_evidence_store(self) -> EvidenceStore:
        if self._evidence_store is None:
            self._evidence_store = EvidenceStore(self._session, self._kernel)
        return self._evidence_store

    async def verify(
        self,
        subject_id: str,
        policy_id: str,
        subject_type: str = "artifact",
        inputs: dict[str, Any] | None = None,
    ) -> SDKVerificationResult:
        """Request independent verification (C6 §54).

        Delegates to the VerificationEngine which runs all checks
        defined by the policy. The agent cannot influence the outcome.
        """
        engine = self._get_engine()

        request = VerificationRequest(
            subject_type=subject_type,
            subject_id=subject_id,
            policy_id=policy_id,
            inputs=inputs or {},
            metadata={
                "execution_id": self._execution_id,
            },
        )

        try:
            result = await engine.verify(request)

            logger.info(
                "verification_completed_via_sdk",
                subject_id=subject_id,
                policy_id=policy_id,
                status=result.status.value,
                checks=len(result.checks),
                failures=len(result.failures),
            )

            return SDKVerificationResult(
                subject_id=subject_id,
                policy_id=policy_id,
                status=result.status.value,
                summary=(
                    f"{len(result.checks)} checks run, "
                    f"{len(result.failures)} failures, "
                    f"{len(result.warnings)} warnings."
                ),
                details={
                    "checks": [
                        {
                            "type": c.check_type,
                            "status": c.status.value,
                            "summary": c.summary,
                        }
                        for c in result.checks
                    ],
                },
                evidence_refs=result.evidence_refs,
                failures=result.failures,
                warnings=result.warnings,
                dimensions=result.dimensions,
                verification_run_id=result.verification_run_id,
            )

        except Exception as e:
            logger.error(
                "verification_sdk_error",
                subject_id=subject_id,
                error=str(e),
            )
            return SDKVerificationResult(
                subject_id=subject_id,
                policy_id=policy_id,
                status=VerificationStatus.INCONCLUSIVE.value,
                summary=f"Verification error: {str(e)[:200]}",
                verification_run_id="",
            )

    async def attach_evidence(
        self,
        claim_id: str,
        evidence_ref: str,
        source_type: str = "agent",
        extracted_content: str = "",
        link_type: str = "supports",
    ) -> SDKEvidenceResult:
        """Attach evidence to a claim (C6 §17, §54)."""
        store = self._get_evidence_store()

        # Create evidence record
        evidence = await store.create_evidence(
            execution_id=self._execution_id,
            source_type=source_type,
            source_ref=evidence_ref,
            extracted_content=extracted_content,
        )

        # Link to claim
        link = await store.link_evidence_to_claim(
            claim_id=claim_id,
            evidence_id=evidence.id,
            link_type=link_type,
        )

        logger.info(
            "evidence_attached_via_sdk",
            claim_id=claim_id,
            evidence_id=evidence.id,
            link_type=link_type,
        )

        return SDKEvidenceResult(
            evidence_id=evidence.id,
            claim_id=claim_id,
            link_type=link_type,
            status="ATTACHED",
        )

    async def get_verification_status(
        self,
        verification_run_id: str,
    ) -> SDKVerificationResult | None:
        """Check status of a previous verification."""
        from sqlalchemy import select
        from core.storage.models.verification import VerificationRun

        stmt = select(VerificationRun).where(
            VerificationRun.id == verification_run_id,
        )
        result = await self._session.execute(stmt)
        run = result.scalar_one_or_none()

        if not run:
            return None

        return SDKVerificationResult(
            subject_id=run.subject_id,
            policy_id=run.policy_id,
            status=run.status,
            verification_run_id=run.id,
        )