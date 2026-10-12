"""
ModelSDK Implementation (C2.12).

Bridge between the Agent's SDK interface (`sdk.model.generate`) and Core's `ModelGateway`.
Translates SDK types to canonical Model Fabric contracts.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.models.gateway.gateway import ModelGateway
from core.storage.identifiers import IdPrefix, new_id
from schemas.domain import (
    MessageRole,
    ModelMessage,
    ModelPolicy,
    ModelRequest,
    ModelRequirements,
)
from sdk.agent.interfaces.model import (
    SDKModelRequest,
    SDKModelResponse,
    SDKModelUsage,
)


class ModelSDKImpl:
    """Concrete implementation of ModelSDK backed by Core's ModelGateway."""

    def __init__(
        self,
        session: AsyncSession,
        execution_id: str,
        task_id: str,
        organization_id: str,
        agent_slug: str,
    ) -> None:
        self._session = session
        self._execution_id = execution_id
        self._task_id = task_id
        self._organization_id = organization_id
        self._agent_slug = agent_slug
        self._gateway = ModelGateway(session)

    async def generate(self, request: SDKModelRequest) -> SDKModelResponse:
        """Execute a model generation request through the Model Gateway."""
        request_id = new_id(IdPrefix.REQUEST)

        # 1. Translate SDK messages to canonical ModelMessage list
        messages: list[ModelMessage] = []
        for msg in request.messages:
            role_str = msg.get("role", "user")
            try:
                role = MessageRole(role_str)
            except ValueError:
                role = MessageRole.USER

            messages.append(
                ModelMessage(
                    role=role,
                    content=msg.get("content", ""),
                    name=msg.get("name"),
                    tool_call_id=msg.get("tool_call_id"),
                )
            )

        # 1.5 Parse metadata for explicit model overrides to construct ModelPolicy
        policy = None
        if request.metadata and "override_model_id" in request.metadata:
            policy = ModelPolicy(
                allowed_models=[request.metadata["override_model_id"]],
                preferred_models=[request.metadata["override_model_id"]],
            )

        # 2. Build canonical ModelRequest
        canonical_req = ModelRequest(
            request_id=request_id,
            execution_id=self._execution_id,
            task_id=self._task_id,
            organization_id=self._organization_id,
            agent_id=self._agent_slug,
            purpose=request.purpose,
            messages=messages,
            system_context=request.system_context,
            response_schema=request.response_schema,
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens,
            requirements=ModelRequirements(
                supports_structured_output=True if request.response_schema else None,
            ),
            model_policy=policy,
            metadata=request.metadata,
        )

        # 3. Execute via ModelGateway
        response = await self._gateway.execute_request(canonical_req)

        # 4. Map ModelResponse back to SDKModelResponse
        sdk_usage = SDKModelUsage(
            input_tokens=response.usage.input_tokens or 0,
            output_tokens=response.usage.output_tokens or 0,
            total_tokens=response.usage.total_tokens or 0,
        )

        tool_calls = [
            {
                "id": tc.id,
                "name": tc.name,
                "arguments": tc.arguments,
            }
            for tc in response.tool_calls
        ]

        return SDKModelResponse(
            output=response.output,
            structured_output=response.structured_output,
            tool_calls=tool_calls,
            finish_reason=response.finish_reason.value,
            usage=sdk_usage,
            model_identifier=response.model_identifier,
            latency_ms=response.latency_ms,
            metadata=response.metadata,
        )