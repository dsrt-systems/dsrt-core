"""
Claim Verifier (C6 §15).

Per-claim verification pipeline — deterministic v1:

    CONTRADICTED          ≥1 evidence link with relationship=contradicts
    OUTDATED              supporting evidence exists but ALL of it is expired
    SUPPORTED             ≥1 live supporting link, all cited refs resolve
    PARTIALLY_SUPPORTED   ≥1 live supporting link, some cited refs unresolved
    INCONCLUSIVE          evidence exists but every piece is INACCESSIBLE
    UNSUPPORTED           no supporting evidence (with or without cited refs)

Semantic support (does the source text actually back the statement?) is the
semantic verifier's job (C6 §12) and is NOT claimed here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import ClaimStatus, EventType, UncertaintyLevel
from schemas.domain.verification import ClaimVerification

from core.api.errors.exceptions import NotFoundError
from core.kernel.kernel import ExecutionKernel
from core.observability.logging import get_logger
from core.repositories.claim_repository import ClaimRepository
from core.verification.evidence.provenance import evidence_is_expired

logger = get_logger("dsrt.verification.claims.verifier")

_UNCERTAINTY = {
    ClaimStatus.SUPPORTED.value: UncertaintyLevel.SUPPORTED.value,
    ClaimStatus.PARTIALLY_SUPPORTED.value: UncertaintyLevel.LIKELY.value,
    ClaimStatus.UNSUPPORTED.value: UncertaintyLevel.UNCERTAIN.value,
    ClaimStatus.CONTRADICTED.value: UncertaintyLevel.CONTRADICTED.value,
    ClaimStatus.OUTDATED.value: UncertaintyLevel.UNCERTAIN.value,
    ClaimStatus.INCONCLUSIVE.value: UncertaintyLevel.UNKNOWN.value,
}


class ClaimVerifier:

    def __init__(
        self,
        session: AsyncSession,
        kernel: ExecutionKernel | None = None,
    ) -> None:
        self._session = session
        self._kernel = kernel
        self._claims = ClaimRepository(session)

    async def verify_claim(
        self,
        claim_id: str,
        organization_id: str,
        verification_run_id: str | None = None,
    ) -> ClaimVerification:
        claim = await self._claims.get_by_id(claim_id)
        if not claim or claim.organization_id != organization_id:
            raise NotFoundError(f"Claim '{claim_id}' not found.")

        rows = await self._claims.get_evidence_for_claim(claim_id)
        now = datetime.now(timezone.utc)

        supporting = [ev for link, ev in rows if link.link_type == "supports"]
        contradicting = [ev for link, ev in rows if link.link_type == "contradicts"]

        cited = set(claim.source_refs or [])
        resolvable = {ev.id for _, ev in rows} | {ev.source_ref for _, ev in rows}
        unresolved = cited - resolvable

        if contradicting:
            status = ClaimStatus.CONTRADICTED
            reason = (
                f"{len(contradicting)} contradicting evidence item(s): "
                f"{[e.id for e in contradicting]}."
            )
        else:
            live = [ev for ev in supporting if not evidence_is_expired(ev, now)]
            if supporting and not live:
                status = ClaimStatus.OUTDATED
                reason = (
                    f"All {len(supporting)} supporting evidence item(s) "
                    f"are past their validity window."
                )
            elif live:
                if cited and unresolved:
                    status = ClaimStatus.PARTIALLY_SUPPORTED
                    reason = (
                        f"{len(live)} live supporting item(s), but cited refs "
                        f"did not resolve: {sorted(unresolved)}."
                    )
                else:
                    status = ClaimStatus.SUPPORTED
                    reason = f"{len(live)} live supporting evidence item(s)."
            else:
                inaccessible_only = bool(rows) and all(
                    ev.verification_status == "INACCESSIBLE" for _, ev in rows
                )
                if inaccessible_only:
                    status = ClaimStatus.INCONCLUSIVE
                    reason = "All linked evidence is marked INACCESSIBLE."
                else:
                    status = ClaimStatus.UNSUPPORTED
                    reason = "No supporting evidence is linked to this claim."

        uncertainty = _UNCERTAINTY[status.value]

        ver_orm = await self._claims.create_verification(
            claim_id=claim_id,
            organization_id=organization_id,
            status=status.value,
            reason=reason,
            supporting_evidence=[ev.id for ev in supporting],
            contradicting_evidence=[ev.id for ev in contradicting],
            uncertainty=uncertainty,
            verification_run_id=verification_run_id,
        )
        await self._claims.update_status(claim, status.value, uncertainty)

        await self._emit(
            claim.execution_id, EventType.CLAIM_VERIFIED,
            {
                "claim_id": claim_id,
                "status": status.value,
                "uncertainty": uncertainty,
                "reason": reason[:200],
            },
        )
        if status == ClaimStatus.CONTRADICTED:
            await self._emit(
                claim.execution_id, EventType.CLAIM_CONTRADICTED,
                {"claim_id": claim_id, "contradicting": [e.id for e in contradicting]},
            )

        logger.info(
            "claim_verified",
            claim_id=claim_id,
            status=status.value,
            supporting=len(supporting),
            contradicting=len(contradicting),
        )
        return ClaimVerification(
            id=ver_orm.id,
            claim_id=claim_id,
            verification_run_id=verification_run_id or "",
            status=status,
            reason=reason,
            supporting_evidence=[ev.id for ev in supporting],
            contradicting_evidence=[ev.id for ev in contradicting],
            uncertainty=UncertaintyLevel(uncertainty),
        )

    async def verify_execution_claims(
        self,
        execution_id: str,
        organization_id: str,
        verification_run_id: str | None = None,
    ) -> list[ClaimVerification]:
        claims = await self._claims.list_for_execution(
            execution_id=execution_id, organization_id=organization_id,
        )
        results: list[ClaimVerification] = []
        for claim in claims:
            try:
                results.append(
                    await self.verify_claim(
                        claim.id, organization_id, verification_run_id,
                    )
                )
            except Exception as e:
                logger.error(
                    "claim_verification_failed",
                    claim_id=claim.id, error=str(e),
                )
        return results

    async def _emit(
        self, execution_id: str, event_type: EventType, payload: dict[str, Any],
    ) -> None:
        if not self._kernel:
            return
        try:
            await self._kernel.emit_event(
                execution_id=execution_id,
                event_type=event_type,
                source="dsrt.verification.claims",
                payload=payload,
            )
        except Exception as e:
            logger.warning(
                "claim_event_emission_failed",
                execution_id=execution_id, error=str(e),
            )