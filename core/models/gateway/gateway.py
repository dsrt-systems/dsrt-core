"""
Model Gateway — The Central Orchestrator of the Model Fabric (C2 §1, §5).

Unites Router, Session Manager, Context Compiler, Credential Broker,
Retry Engine, Usage Meter, and Event Telemetry into a single unified entry point.
"""

from __future__ import annotations

import sys
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.api.errors.exceptions import DSRTError, NotFoundError
from core.config import get_settings
from core.kernel.fingerprint import content_hash, payload_hash
from core.kernel.kernel import ExecutionKernel
from core.models.context.compiler import ContextCompiler
from core.models.credentials.broker import CredentialBroker
from core.models.fallback.resolver import FallbackResolver
from core.models.registry.registry import ModelRegistry
from core.models.retry.engine import RetryEngine
from core.models.router.router import ModelRouter
from core.models.sessions.manager import ModelSessionManager
from core.models.usage.meter import UsageMeter
from core.observability.logging import get_logger
from core.providers.registry.registry import adapter_registry
from core.repositories import (
    CredentialRepository,
    EventRepository,
    ExecutionRepository,
    ProviderRepository,
    SessionRepository,
    TaskRepository,
    UsageRepository,
)
from schemas.domain import (
    EventType,
    ModelCheckpointCreate,
    ModelPolicy,
    ModelRequest,
    ModelRequirements,
    ModelResponse,
)


logger = get_logger("dsrt.models.gateway")


class ModelGateway:
    """The Model Fabric Gateway orchestrating end-to-end model execution."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        
        # Repositories
        self._provider_repo = ProviderRepository(session)
        self._cred_repo = CredentialRepository(session)
        self._session_repo = SessionRepository(session)
        self._usage_repo = UsageRepository(session)
        self._task_repo = TaskRepository(session)
        self._exe_repo = ExecutionRepository(session)
        self._event_repo = EventRepository(session)

        # Services
        self._registry = ModelRegistry(self._provider_repo)
        self._router = ModelRouter(self._provider_repo)
        self._session_manager = ModelSessionManager(self._session_repo)
        self._compiler = ContextCompiler()
        self._broker = CredentialBroker(self._cred_repo)
        self._fallback_resolver = FallbackResolver(self._router)
        self._retry_engine = RetryEngine(fallback_resolver=self._fallback_resolver)
        self._meter = UsageMeter(self._usage_repo, self._registry)
        
        # Kernel for event emission
        self._kernel = ExecutionKernel(
            task_repo=self._task_repo,
            execution_repo=self._exe_repo,
            agent_registry=None,  # Not needed for event emission
            event_repo=self._event_repo,
        )

    async def execute_request(
        self,
        request: ModelRequest,
        credential_id: str | None = None,
        override_api_key: str | None = None,
    ) -> ModelResponse:
        """Execute a canonical ModelRequest through the complete Model Fabric pipeline."""
        
        # 1. Emit MODEL_REQUEST_CREATED
        await self._kernel.emit_event(
            execution_id=request.execution_id,
            event_type=EventType.MODEL_REQUEST_CREATED,
            source="dsrt.models.gateway",
            payload={"request_id": request.request_id, "purpose": request.purpose},
            request_id=request.request_id,
        )

        # 2. Model Routing
        await self._kernel.emit_event(
            execution_id=request.execution_id,
            event_type=EventType.MODEL_ROUTING_STARTED,
            source="dsrt.models.gateway",
            payload={"purpose": request.purpose},
            request_id=request.request_id,
        )

        route_selection = await self._router.route(
            request,
            policy=request.model_policy,
            requirements=request.requirements,
        )
        selected_model = route_selection.selected_model
        selected_provider = route_selection.selected_provider
        decision = route_selection.decision

        await self._kernel.emit_event(
            execution_id=request.execution_id,
            event_type=EventType.MODEL_ROUTING_COMPLETED,
            source="dsrt.models.gateway",
            payload={
                "selected_model": selected_model.slug,
                "selected_provider": selected_provider.slug,
                "decision_latency_ms": decision.decision_latency_ms,
                "reason_codes": [r.value for r in decision.reason_codes],
            },
            request_id=request.request_id,
        )

        # 3. Model Session Management & Switching Check
        # Inspect active session before resolving to determine if a transition occurs
        active_sess = await self._session_repo.get_active_session(request.execution_id)
        is_switch = active_sess is not None and active_sess.model_id != selected_model.id

        session = await self._session_manager.get_or_create_active_session(
            execution_id=request.execution_id,
            target_model_id=selected_model.id,
            target_provider_id=selected_provider.id,
        )

        if is_switch:
            await self._kernel.emit_event(
                execution_id=request.execution_id,
                event_type=EventType.MODEL_SESSION_SWITCHED,
                source="dsrt.models.gateway",
                payload={
                    "new_session_id": session.id,
                    "target_model_id": selected_model.id,
                },
                request_id=request.request_id,
            )

        # 4. Resolve Credential (BYOK / Managed / Testing fallback)
        api_key = override_api_key
        if not api_key and request.metadata:
            api_key = request.metadata.get("override_api_key")

        if not api_key and credential_id:
            api_key = await self._broker.resolve_secret_key(
                organization_id=request.organization_id,
                credential_id=credential_id,
            )

        if not api_key:
            # Check for active org credential in database
            try:
                creds = await self._cred_repo.list_by_organization(request.organization_id)
                for c in creds:
                    if c.provider_id == selected_provider.id and c.status == "active":
                        api_key = await self._broker.resolve_secret_key(
                            organization_id=request.organization_id,
                            credential_id=c.id,
                        )
                        break
            except Exception:
                pass

        if not api_key:
            settings = get_settings()
            if settings.testing or "pytest" in sys.modules:
                api_key = "sk-dsrt-test-dummy-key"

        # 5. Fetch Provider Adapter
        adapter = adapter_registry.get_adapter(selected_provider.slug)
        if not adapter:
            raise NotFoundError(f"Adapter for provider '{selected_provider.slug}' not registered.")

        # Set selected model identifier on request for adapter
        setattr(request, "_selected_model_identifier", selected_model.model_identifier)

        # 6. Execute Generation via Retry Engine
        await self._kernel.emit_event(
            execution_id=request.execution_id,
            event_type=EventType.MODEL_REQUEST_STARTED,
            source="dsrt.models.gateway",
            payload={
                "model_identifier": selected_model.model_identifier,
                "provider_slug": selected_provider.slug,
            },
            request_id=request.request_id,
        )

        retry_result = await self._retry_engine.execute_with_retry(
            adapter=adapter,
            request=request,
            api_key=api_key,
            model_id=selected_model.id,
            provider_id=selected_provider.id,
            model_identifier=selected_model.model_identifier,
        )

        # Emit retry/fallback telemetry events if occurred
        for attempt_rec in retry_result.attempts:
            if not attempt_rec.success and attempt_rec.error:
                await self._kernel.emit_event(
                    execution_id=request.execution_id,
                    event_type=EventType.MODEL_REQUEST_RETRY,
                    source="dsrt.models.gateway",
                    payload={
                        "attempt": attempt_rec.attempt_number,
                        "error_code": attempt_rec.error.code.value,
                        "message": attempt_rec.error.message,
                    },
                    request_id=request.request_id,
                )

        if retry_result.fallback_used:
            await self._kernel.emit_event(
                execution_id=request.execution_id,
                event_type=EventType.MODEL_FALLBACK_COMPLETED,
                source="dsrt.models.gateway",
                payload={"fallback_used": True},
                request_id=request.request_id,
            )

        if not retry_result.succeeded or not retry_result.response:
            await self._kernel.emit_event(
                execution_id=request.execution_id,
                event_type=EventType.MODEL_REQUEST_FAILED,
                source="dsrt.models.gateway",
                payload={"error": str(retry_result.final_error)},
                request_id=request.request_id,
            )
            raise retry_result.final_error or DSRTError("Model request failed after retries.")

        # Use model_copy to update immutable ModelResponse fields safely
        response = retry_result.response.model_copy(
            update={
                "model_id": selected_model.id,
                "provider_id": selected_provider.id,
            }
        )

        # 7. Meter Usage & Cost Accounting
        await self._meter.record_model_response(
            organization_id=request.organization_id,
            execution_id=request.execution_id,
            response=response,
        )

        # 8. Create Checkpoint
        context_hash_str = payload_hash([m.model_dump() for m in request.messages])
        output_hash_str = content_hash(response.output or "")
        
        chk = await self._session_manager.create_checkpoint(
            ModelCheckpointCreate(
                session_id=session.id,
                request_id=request.request_id,
                context_hash=context_hash_str,
                canonical_state_hash=context_hash_str,
                output_hash=output_hash_str,
                metadata={"tokens": response.usage.total_tokens},
            )
        )

        await self._kernel.emit_event(
            execution_id=request.execution_id,
            event_type=EventType.MODEL_CHECKPOINT_CREATED,
            source="dsrt.models.gateway",
            payload={"checkpoint_id": chk.id, "session_id": session.id},
            request_id=request.request_id,
        )

        # 9. Emit MODEL_REQUEST_COMPLETED
        await self._kernel.emit_event(
            execution_id=request.execution_id,
            event_type=EventType.MODEL_REQUEST_COMPLETED,
            source="dsrt.models.gateway",
            payload={
                "finish_reason": response.finish_reason.value,
                "total_tokens": response.usage.total_tokens,
                "model_identifier": response.model_identifier,
            },
            request_id=request.request_id,
        )

        return response