"""
Verification Engine (C6 §7-9, §12-13, §30-32).

The central orchestrator for independent verification.

Architecture (C6 §12-13):
  1. Receive VerificationRequest
  2. Resolve VerificationPolicy (unknown policy → NotFoundError, never a default)
  3. Create VerificationRun (PENDING)
  4. Transition to RUNNING
  5. Execute required checks (deterministic first)
  6. Execute optional checks
  7. Aggregate results (policy-driven, NOT majority-vote)
  8. Determine final status
  9. Persist results
 10. Emit events

Key principle (C6 §13):
  The engine NEVER trusts the producer's self-assessment.
  Verification is independent from execution.

Identity binding:
  The engine is constructed with the execution_id and organization_id it
  serves. These are NEVER read from request metadata (which is
  agent-controllable); they are bound once by the caller (kernel / API
  layer) and applied to every VerificationRun this engine creates.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.enums import CheckType, EventType, VerificationStatus
from schemas.domain.verification import (
    C6VerificationResult,
    VerificationCheckResult,
    VerificationPolicy,
    VerificationRequest,
    VerificationThresholds,
)

from core.api.errors.exceptions import NotFoundError
from core.kernel.kernel import ExecutionKernel
from core.observability.logging import get_logger
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.verification import (
    VerificationCheckORM,
    VerificationPolicyORM,
    VerificationResult,
    VerificationRun,
)
from core.verification.checks.base import BaseCheck  # single source of truth
from core.verification.engine.lifecycle import VerificationLifecycleManager
from core.verification.engine.request import VerificationRequestProcessor


logger = get_logger("dsrt.verification.engine")


class VerificationEngine:
    """The central verification orchestrator (C6 §7).

    The engine is bound to a single execution and tenant at construction
    time. Callers MUST supply both ``execution_id`` and ``organization_id``;
    they are never derived from the (agent-controllable) request metadata.

    Usage:
        engine = VerificationEngine(
            session,
            kernel,
            execution_id=execution_id,
            organization_id=organization_id,
        )
        engine.register_check(SchemaCheck())
        engine.register_check(ArtifactCheck())
        result = await engine.verify(request)
    """

    def __init__(
        self,
        session: AsyncSession,
        kernel: ExecutionKernel | None = None,
        *,
        execution_id: str,
        organization_id: str,
    ) -> None:
        self._session = session
        self._kernel = kernel
        self._execution_id = execution_id
        self._organization_id = organization_id
        self._lifecycle = VerificationLifecycleManager()
        self._request_processor = VerificationRequestProcessor()

        # Check registry: check_type -> BaseCheck instance
        self._checks: dict[str, BaseCheck] = {}

    def register_check(self, check: BaseCheck) -> None:
        """Register a verification check implementation.

        Checks are registered by their check_type. Only one check
        per type is allowed (last registration wins).
        """
        self._checks[check.check_type] = check
        logger.debug(
            "verification_check_registered",
            check_type=check.check_type,
        )

    def get_registered_checks(self) -> list[str]:
        """Return the list of registered check types."""
        return list(self._checks.keys())

    async def verify(
        self,
        request: VerificationRequest,
    ) -> C6VerificationResult:
        """Execute the full verification pipeline (C6 §7-9).

        Pipeline:
          1. Validate & normalize request
          2. Resolve policy (unknown policy → NotFoundError)
          3. Create VerificationRun
          4. Run required checks
          5. Run optional checks
          6. Aggregate results
          7. Persist & emit events

        Raises:
            NotFoundError: if the requested policy does not exist. A missing
                policy is never silently replaced with a permissive default
                (C6 §13) — that would be a self-verification bypass.

        Returns:
            C6VerificationResult with multi-dimensional assessment.
        """
        start_time = time.perf_counter()

        # 1. Validate & normalize request
        request = self._request_processor.process(request)

        # 2. Resolve policy (C6 §13: unknown policy is an error, never a default)
        policy = await self._resolve_policy(request.policy_id)
        if policy is None:
            raise NotFoundError(
                f"Verification policy '{request.policy_id}' not found.",
                metadata={"policy_id": request.policy_id},
            )

        # 3. Create VerificationRun (identity bound at construction, not from
        #    request metadata)
        run_id = new_id(IdPrefix.VERIFICATION_RUN)
        run_orm = VerificationRun(
            id=run_id,
            execution_id=self._execution_id,
            subject_type=request.subject_type,
            subject_id=request.subject_id,
            policy_id=request.policy_id,
            status=VerificationStatus.PENDING.value,
            engine_version="1.0.0",
            started_at=datetime.now(timezone.utc),
            organization_id=self._organization_id,
            inputs=request.inputs,
            constraints_list=request.constraints,
            context_ref=request.context_ref,
            metadata_json=request.metadata,
        )
        self._session.add(run_orm)
        await self._session.flush()

        # Transition to RUNNING
        self._lifecycle.validate_transition(
            VerificationStatus.PENDING.value,
            VerificationStatus.RUNNING.value,
        )
        run_orm.status = VerificationStatus.RUNNING.value
        await self._session.flush()

        # Emit VERIFICATION_STARTED event
        await self._emit_event(
            self._execution_id,
            EventType.VERIFICATION_STARTED,
            {
                "verification_run_id": run_id,
                "subject_type": request.subject_type,
                "subject_id": request.subject_id,
                "policy_id": request.policy_id,
            },
        )

        # 4. Run required checks
        check_results: list[VerificationCheckResult] = []
        failures: list[str] = []
        warnings: list[str] = []

        for check_type_str in policy.required_checks:
            result = await self._run_check(
                check_type_str=check_type_str,
                run_id=run_id,
                subject_type=request.subject_type,
                subject_id=request.subject_id,
                inputs=request.inputs,
                policy=policy,
                required=True,
            )
            check_results.append(result)

            if result.status == VerificationStatus.FAILED.value:
                failures.append(f"{check_type_str}: {result.summary}")
            elif result.status == VerificationStatus.PASSED_WITH_WARNINGS.value:
                warnings.append(f"{check_type_str}: {result.summary}")

        # 5. Run optional checks
        for check_type_str in policy.optional_checks:
            result = await self._run_check(
                check_type_str=check_type_str,
                run_id=run_id,
                subject_type=request.subject_type,
                subject_id=request.subject_id,
                inputs=request.inputs,
                policy=policy,
                required=False,
            )
            check_results.append(result)

            # Optional check failures become warnings, not hard failures
            if result.status == VerificationStatus.FAILED.value:
                warnings.append(
                    f"[optional] {check_type_str}: {result.summary}"
                )

        # 6. Aggregate results (C6 §32)
        check_statuses = [r.status for r in check_results]
        has_warnings = len(warnings) > 0

        # Check if any required deterministic check failed
        deterministic_failed = any(
            r.status == VerificationStatus.FAILED.value
            and r.evaluator == "deterministic"
            and r.required
            for r in check_results
        )

        requires_review = any(
            r.status == VerificationStatus.INCONCLUSIVE.value
            and r.required
            for r in check_results
        )

        if deterministic_failed and policy.deterministic_must_pass:
            final_status = VerificationStatus.FAILED.value
        else:
            final_status = self._lifecycle.determine_final_status(
                check_statuses=check_statuses,
                has_warnings=has_warnings,
                requires_review=requires_review,
            )

        # Build multi-dimensional scores (C6 §5)
        dimensions = self._compute_dimensions(check_results)

        # 7. Persist results
        duration_ms = int((time.perf_counter() - start_time) * 1000)

        # Update run status
        self._lifecycle.validate_transition(
            VerificationStatus.RUNNING.value,
            final_status,
        )
        run_orm.status = final_status
        run_orm.completed_at = datetime.now(timezone.utc)

        # Persist C1-compatible VerificationResult records
        for cr in check_results:
            result_orm = VerificationResult(
                id=new_id(IdPrefix.VERIFICATION_RESULT),
                verification_run_id=run_id,
                check_type=cr.check_type,
                status=cr.status,
                summary=cr.summary,
                details=cr.details,
                evidence_refs=cr.evidence_refs,
                evaluator=cr.evaluator,
                required=cr.required,
                uncertainty=cr.uncertainty,
                duration_ms=cr.duration_ms,
                failures=[cr.summary] if cr.status == VerificationStatus.FAILED.value else [],
                warnings=[cr.summary] if cr.status == VerificationStatus.PASSED_WITH_WARNINGS.value else [],
            )
            self._session.add(result_orm)

        await self._session.flush()

        # Emit VERIFICATION_COMPLETED event
        await self._emit_event(
            self._execution_id,
            EventType.VERIFICATION_COMPLETED,
            {
                "verification_run_id": run_id,
                "status": final_status,
                "checks_run": len(check_results),
                "failures": len(failures),
                "warnings": len(warnings),
                "duration_ms": duration_ms,
            },
        )

        logger.info(
            "verification_completed",
            run_id=run_id,
            execution_id=self._execution_id,
            organization_id=self._organization_id,
            status=final_status,
            checks=len(check_results),
            failures=len(failures),
            warnings=len(warnings),
            duration_ms=duration_ms,
        )

        return C6VerificationResult(
            id=new_id(IdPrefix.VERIFICATION_RESULT),
            verification_run_id=run_id,
            status=VerificationStatus(final_status),
            checks=check_results,
            evidence_refs=request.evidence_refs,
            failures=failures,
            warnings=warnings,
            required_actions=[],  # Populated by C6.7 RecoveryDecider
            dimensions=dimensions,
            policy_id=request.policy_id,
            engine_version="1.0.0",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------
    # Internal Methods
    # ------------------------------------------------------------------

    async def _run_check(
        self,
        check_type_str: str,
        run_id: str,
        subject_type: str,
        subject_id: str,
        inputs: dict[str, Any],
        policy: VerificationPolicy,
        required: bool,
    ) -> VerificationCheckResult:
        """Run a single verification check and persist the result."""
        check_start = time.perf_counter()

        check_impl = self._checks.get(check_type_str)

        if not check_impl:
            # Check not registered — mark as INCONCLUSIVE
            logger.warning(
                "verification_check_not_registered",
                check_type=check_type_str,
                run_id=run_id,
            )
            return VerificationCheckResult(
                check_id=new_id(IdPrefix.VERIFICATION_CHECK),
                check_type=check_type_str,
                evaluator="none",
                required=required,
                status=VerificationStatus.INCONCLUSIVE,
                summary=f"Check '{check_type_str}' is not registered.",
                details={"reason": "not_implemented"},
            )

        try:
            result = await check_impl.execute(
                subject_type=subject_type,
                subject_id=subject_id,
                inputs=inputs,
                policy=policy,
            )
            result.check_id = new_id(IdPrefix.VERIFICATION_CHECK)
            result.required = required
            result.duration_ms = int((time.perf_counter() - check_start) * 1000)

            # Persist check record
            check_orm = VerificationCheckORM(
                id=result.check_id,
                verification_run_id=run_id,
                check_type=result.check_type,
                evaluator=result.evaluator,
                required=required,
                status=result.status.value,
                summary=result.summary,
                details=result.details,
                evidence_refs=result.evidence_refs,
                uncertainty=result.uncertainty.value,
                duration_ms=result.duration_ms,
            )
            self._session.add(check_orm)

            return result

        except Exception as e:
            logger.error(
                "verification_check_error",
                check_type=check_type_str,
                run_id=run_id,
                error=str(e),
            )
            return VerificationCheckResult(
                check_id=new_id(IdPrefix.VERIFICATION_CHECK),
                check_type=check_type_str,
                evaluator="error",
                required=required,
                status=VerificationStatus.FAILED,
                summary=f"Check execution error: {str(e)[:200]}",
                details={"error": str(e)},
                duration_ms=int((time.perf_counter() - check_start) * 1000),
            )

    async def _resolve_policy(
        self, policy_id: str,
    ) -> VerificationPolicy | None:
        """Resolve a verification policy from the database.

        Returns ``None`` if the policy does not exist; the caller is
        responsible for treating that as an error (never a default).
        """
        stmt = select(VerificationPolicyORM).where(
            VerificationPolicyORM.id == policy_id,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

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

    def _compute_dimensions(
        self, check_results: list[VerificationCheckResult],
    ) -> dict[str, float]:
        """Compute multi-dimensional verification scores (C6 §5).

        Each dimension is computed independently. Never collapsed to one score.
        """
        dimensions: dict[str, float] = {}

        if not check_results:
            return dimensions

        # Group by check type category
        correctness_checks = [
            r for r in check_results
            if r.check_type in (
                CheckType.SCHEMA_VALID.value,
                CheckType.CLAIM_SUPPORTED.value,
                CheckType.SEMANTIC_CORRECTNESS.value,
            )
        ]
        completeness_checks = [
            r for r in check_results
            if r.check_type == CheckType.COMPLETENESS.value
        ]
        evidence_checks = [
            r for r in check_results
            if r.check_type in (
                CheckType.CITATION_PRESENT.value,
                CheckType.CITATION_VALID.value,
                CheckType.SOURCE_ACCESSIBLE.value,
                CheckType.CONTRADICTION_CHECK.value,
            )
        ]
        integrity_checks = [
            r for r in check_results
            if r.check_type in (
                CheckType.ARTIFACT_PARSEABLE.value,
                CheckType.ARTIFACT_INTEGRITY.value,
                CheckType.STATE_CONSISTENT.value,
            )
        ]

        def pass_rate(checks: list[VerificationCheckResult]) -> float:
            if not checks:
                return 1.0
            passed = sum(
                1 for c in checks
                if c.status in (
                    VerificationStatus.PASSED.value,
                    VerificationStatus.PASSED_WITH_WARNINGS.value,
                )
            )
            return passed / len(checks)

        if correctness_checks:
            dimensions["correctness"] = pass_rate(correctness_checks)
        if completeness_checks:
            dimensions["completeness"] = pass_rate(completeness_checks)
        if evidence_checks:
            dimensions["evidence_quality"] = pass_rate(evidence_checks)
        if integrity_checks:
            dimensions["integrity"] = pass_rate(integrity_checks)

        # Overall pass rate (informational, not a "quality score")
        dimensions["overall_pass_rate"] = pass_rate(check_results)

        return dimensions

    async def _emit_event(
        self,
        execution_id: str,
        event_type: EventType,
        payload: dict[str, Any],
    ) -> None:
        """Emit a verification event into the execution trajectory."""
        if not self._kernel:
            return
        try:
            await self._kernel.emit_event(
                execution_id=execution_id,
                event_type=event_type,
                source="dsrt.verification.engine",
                payload=payload,
            )
        except Exception as e:
            logger.warning(
                "verification_event_emission_failed",
                execution_id=execution_id,
                error=str(e),
            )