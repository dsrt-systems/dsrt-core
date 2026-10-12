"""
Research Intelligence Agent — DSRTAgent implementation (C2.12 Update).

Uses ONLY the sdk.agent public surface. Zero core or provider imports.
Demonstrates model-neutral reasoning via sdk.model.generate().
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agents.research_intelligence.runtime.analyzer import EvidenceAnalyzer
from agents.research_intelligence.runtime.finalizer import ResearchFinalizer
from agents.research_intelligence.runtime.models import ResearchState
from agents.research_intelligence.runtime.planner import ResearchPlanner
from agents.research_intelligence.verification.verifier import ResearchVerifier
from schemas.domain import (
    AgentIdentity,
    AgentManifest,
    AgentPermissions,
    AgentRequirements,
    ArtifactType,
    BrowserPermission,
    ExternalActionsPermission,
    FilesystemPermission,
    NetworkPermission,
)
from sdk.agent import (
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentHealth,
    AgentInitializationRequest,
    AgentInitializationResult,
    DSRTAgentSDK,
    SDKModelRequest,
)


_MANIFEST_PATH = Path(__file__).resolve().parents[1] / "manifest.yaml"


def _load_manifest() -> AgentManifest:
    """Load and validate the agent manifest from disk."""
    with _MANIFEST_PATH.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    identity_raw = raw["identity"]
    reqs_raw = raw.get("requirements", {})
    perms_raw = raw.get("permissions", {})

    identity = AgentIdentity(
        id=identity_raw["id"],
        name=identity_raw["name"],
        version=identity_raw["version"],
        contract_version=identity_raw["contract_version"],
        publisher=identity_raw["publisher"],
        category=identity_raw["category"],
    )
    requirements = AgentRequirements(
        minimum_core_version=reqs_raw.get("minimum_core_version", "1.0.0"),
        required_capabilities=list(reqs_raw.get("required_capabilities", [])),
        optional_capabilities=list(reqs_raw.get("optional_capabilities", [])),
        required_tools=list(reqs_raw.get("required_tools", [])),
        optional_tools=list(reqs_raw.get("optional_tools", [])),
    )

    net = perms_raw.get("network") or {}
    fs = perms_raw.get("filesystem") or {}
    br = perms_raw.get("browser") or {}
    ext = perms_raw.get("external_actions") or {}

    permissions = AgentPermissions(
        network=NetworkPermission(required=bool(net.get("required", False))),
        filesystem=FilesystemPermission(access=str(fs.get("access", "none"))),
        browser=BrowserPermission(access=bool(br.get("access", False))),
        external_actions=ExternalActionsPermission(access=bool(ext.get("access", False))),
    )

    return AgentManifest(
        identity=identity,
        capabilities=list(raw.get("capabilities", [])),
        requirements=requirements,
        permissions=permissions,
        configuration=dict(raw.get("configuration", {})),
        description=str(raw.get("description", "")).strip(),
    )


_MANIFEST = _load_manifest()


class ResearchIntelligenceAgent:
    """DSRT Research Intelligence Agent v1.0."""

    identity = _MANIFEST.identity
    manifest = _MANIFEST

    def __init__(self) -> None:
        cfg = _MANIFEST.configuration
        self._planner = ResearchPlanner(
            min_questions=int(cfg.get("min_questions", 2)),
            max_questions=int(cfg.get("max_questions", 6)),
        )
        self._analyzer = EvidenceAnalyzer()
        self._verifier = ResearchVerifier()
        self._finalizer = ResearchFinalizer()

        self._sdk: DSRTAgentSDK | None = None
        self._cancelled = False

    async def initialize(
        self,
        sdk: DSRTAgentSDK,
        request: AgentInitializationRequest,
    ) -> AgentInitializationResult:
        self._sdk = sdk
        self._cancelled = False

        if sdk.contract_version != self.identity.contract_version:
            return AgentInitializationResult(
                status="FAILED",
                message=(
                    f"Contract version mismatch: agent={self.identity.contract_version} "
                    f"sdk={sdk.contract_version}"
                ),
            )

        sdk.logging.info(
            "research_agent_initialized",
            agent_version=self.identity.version,
            sdk_version=sdk.sdk_version,
        )
        await sdk.events.emit(
            "AGENT_READY",
            {
                "agent_id": self.identity.id,
                "agent_version": self.identity.version,
                "workflow": _MANIFEST.configuration.get("default_workflow"),
            },
        )
        return AgentInitializationResult(
            status="READY",
            message="Research Intelligence Agent ready.",
            metadata={
                "agent_version": self.identity.version,
                "capabilities": list(self.manifest.capabilities),
            },
        )

    async def execute(
        self, request: AgentExecutionRequest,
    ) -> AgentExecutionResult:
        if self._sdk is None:
            return AgentExecutionResult(
                status="FAILED",
                error_code="AGENT_NOT_INITIALIZED",
                error_message="initialize() must be called before execute().",
            )
        sdk = self._sdk

        if self._cancelled:
            return AgentExecutionResult(
                status="CANCELLED",
                error_code="EXECUTION_CANCELLED",
                error_message="Cancelled before execution began.",
            )

        try:
            # 1. Understand objective
            ctx = await sdk.context.get()
            objective = request.objective or ctx.objective
            input_payload = request.input_payload or ctx.input_payload or {}

            sdk.logging.info("research_started", objective=objective)
            await sdk.events.emit("RESEARCH_STARTED", {"objective": objective})

            state = ResearchState(objective=objective, status="PLANNING")

            # 2. Plan
            plan = self._planner.create_plan(objective, input_payload)
            state.plan = plan
            state.questions = list(plan.questions)
            state.status = "RESEARCHING"

            await sdk.events.emit(
                "RESEARCH_PLAN_CREATED",
                {
                    "workflow": plan.workflow,
                    "question_count": len(plan.questions),
                    "questions": [
                        {"id": q.id, "text": q.text, "priority": q.priority}
                        for q in plan.questions
                    ],
                },
            )

            if self._cancelled:
                return self._cancelled_result()

            # 3. Analyze evidence
            state.status = "ANALYZING"
            self._analyzer.analyze(state, input_payload)

            # --- C2 Model Fabric Intelligence Request ---
            # Ask model for executive summary reasoning if enabled
            if input_payload.get("use_model_reasoning", False):
                try:
                    model_resp = await sdk.model.generate(
                        SDKModelRequest(
                            purpose="executive_synthesis",
                            messages=[
                                {
                                    "role": "user",
                                    "content": f"Provide an executive summary for research objective: {objective}",
                                }
                            ],
                            temperature=0.3,
                        )
                    )
                    if model_resp.output:
                        sdk.logging.info("model_reasoning_succeeded", model=model_resp.model_identifier)
                        await sdk.events.emit(
                            "MODEL_REASONING_COMPLETED",
                            {"model_identifier": model_resp.model_identifier},
                        )
                except Exception as me:
                    sdk.logging.warning("model_reasoning_skipped_or_failed", error=str(me))

            await sdk.events.emit(
                "EVIDENCE_ANALYZED",
                {
                    "sources": len(state.sources),
                    "evidence": len(state.evidence),
                    "claims": len(state.claims),
                    "citations": len(state.citations),
                    "contradictions": len(state.contradictions),
                    "unresolved_questions": len(state.unresolved_questions),
                },
            )

            if self._cancelled:
                return self._cancelled_result()

            # 4. Verify
            state.status = "VERIFYING"
            verification = self._verifier.verify(state)
            state.verification_report = {
                "status": verification.status,
                "failures": list(verification.failures),
                "warnings": list(verification.warnings),
                "checks": [
                    {"check": c.check, "passed": c.passed, "details": c.details}
                    for c in verification.checks
                ],
            }

            await sdk.events.emit(
                "RESEARCH_VERIFIED",
                {
                    "status": verification.status,
                    "failure_count": len(verification.failures),
                    "warning_count": len(verification.warnings),
                },
            )

            # 5. Benchmark hooks
            await sdk.benchmark.record(
                "research.questions_answered",
                value=len(state.questions) - len(state.unresolved_questions),
                total=len(state.questions),
            )
            await sdk.benchmark.record(
                "research.claim_evidence_ratio",
                value=len(state.evidence) / max(len(state.claims), 1),
                claims=len(state.claims),
                evidence=len(state.evidence),
            )
            await sdk.benchmark.record(
                "research.verification_status",
                value=verification.status,
            )

            if verification.status == "FAILED":
                await sdk.events.emit(
                    "RESEARCH_FAILED_VERIFICATION",
                    {"failures": verification.failures},
                )
                return AgentExecutionResult(
                    status="FAILED",
                    error_code="AGENT_EXECUTION_FAILED",
                    error_message=(
                        "Research verification failed: "
                        + "; ".join(verification.failures[:3])
                    ),
                    result_summary={
                        "verification": state.verification_report,
                        "unresolved_questions": state.unresolved_questions,
                    },
                )

            # 6. Finalize
            state.status = "FINALIZING"
            report_body = self._finalizer.render_report(state, verification)

            artifact = await sdk.artifacts.create(
                name=f"research_report_{self.identity.version}.md",
                artifact_type=ArtifactType.REPORT.value,
                content=report_body,
                mime_type="text/markdown",
                provenance={
                    "objective": objective,
                    "workflow": plan.workflow,
                    "question_count": len(plan.questions),
                    "source_count": len(state.sources),
                    "claim_count": len(state.claims),
                    "citation_count": len(state.citations),
                    "verification_status": verification.status,
                },
                metadata={
                    "unresolved_questions": state.unresolved_questions,
                    "contradiction_count": len(state.contradictions),
                },
            )

            state.status = "COMPLETED"
            await sdk.events.emit(
                "RESEARCH_COMPLETED",
                {
                    "artifact_id": artifact.id,
                    "verification_status": verification.status,
                },
            )

            return AgentExecutionResult(
                status="COMPLETED",
                result_summary={
                    "artifact_id": artifact.id,
                    "verification": state.verification_report,
                    "question_count": len(state.questions),
                    "claim_count": len(state.claims),
                    "citation_count": len(state.citations),
                    "contradiction_count": len(state.contradictions),
                    "unresolved_questions": state.unresolved_questions,
                },
                artifacts_created=[artifact.id],
            )

        except Exception as e:
            sdk.logging.error("research_execution_error", error=str(e))
            return AgentExecutionResult(
                status="FAILED",
                error_code="AGENT_EXECUTION_FAILED",
                error_message=str(e),
            )

    async def cancel(self) -> None:
        self._cancelled = True
        if self._sdk is not None:
            self._sdk.logging.info("research_agent_cancel_requested")

    async def health(self) -> AgentHealth:
        return AgentHealth(
            status="healthy",
            details={
                "agent_version": self.identity.version,
                "contract_version": self.identity.contract_version,
                "initialized": self._sdk is not None,
                "cancelled": self._cancelled,
            },
        )

    def _cancelled_result(self) -> AgentExecutionResult:
        return AgentExecutionResult(
            status="CANCELLED",
            error_code="EXECUTION_CANCELLED",
            error_message="Execution cancelled during processing.",
        )