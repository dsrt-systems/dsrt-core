"""
Google Gemini Provider Adapter (C2.4).

Translates DSRT canonical requests into Google GenAI (Gemini) API payloads.
Proves model-independence across radically different provider architectures.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from google import genai
from google.genai import errors, types

from core.api.errors.exceptions import DSRTError
from core.providers.base.adapter import ModelProviderAdapter
from schemas.domain import (
    FinishReason,
    MessageContentType,
    MessageRole,
    ModelError,
    ModelErrorCode,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ProviderHealth,
    ProviderHealthStatus,
    RetryClassification,
    StreamEvent,
    TokenCountRequest,
    TokenCountResponse,
    ToolCall,
    Usage,
)


class GoogleAdapter(ModelProviderAdapter):
    """Google Gemini API implementation of the DSRT Model Provider Adapter."""

    PROVIDER_ID = "prv_google_internal"
    PROVIDER_SLUG = "google"

    def __init__(self, default_api_key: str | None = None) -> None:
        self._default_api_key = default_api_key

    def _get_client(self, api_key: str | None) -> genai.Client:
        """Initialize transient client to prevent key leakage across requests."""
        key = api_key or self._default_api_key
        if not key:
            raise ValueError(
                "Google API key missing. Must provide BYOK or set managed default."
            )
        return genai.Client(api_key=key)

    def _translate_role(self, role: MessageRole) -> str:
        """Map DSRT roles to Gemini roles."""
        if role == MessageRole.SYSTEM:
            return "system"
        elif role in (MessageRole.USER, MessageRole.TOOL):
            return "user"
        elif role == MessageRole.ASSISTANT:
            return "model"
        return "user"

    def _translate_messages(self, messages: list[ModelMessage]) -> list[types.Content]:
        """Translate DSRT messages to Gemini Content objects."""
        out: list[types.Content] = []

        for msg in messages:
            parts: list[types.Part] = []

            if isinstance(msg.content, str):
                parts.append(types.Part(text=msg.content))

            elif isinstance(msg.content, list):
                for part in msg.content:
                    if part.type == MessageContentType.TEXT and part.text:
                        parts.append(types.Part(text=part.text))

                    elif part.type == MessageContentType.IMAGE_URL and part.image_url:
                        raise NotImplementedError(
                            "Google API requires image bytes or gs:// URIs, not HTTP URLs."
                        )

                    elif (
                        part.type == MessageContentType.IMAGE_BYTES
                        and part.image_bytes_base64
                        and part.image_mime_type
                    ):
                        raw_bytes = base64.b64decode(part.image_bytes_base64)
                        parts.append(
                            types.Part.from_bytes(
                                data=raw_bytes, mime_type=part.image_mime_type
                            )
                        )

                    elif (
                        part.type == MessageContentType.TOOL_RESULT
                        and part.tool_call_id
                        and part.tool_result
                    ):
                        parts.append(
                            types.Part.from_function_response(
                                name=part.tool_call_id,
                                response=part.tool_result,
                            )
                        )

            if msg.role == MessageRole.ASSISTANT and msg.tool_call_id:
                args = {}
                if isinstance(msg.content, str):
                    try:
                        args = json.loads(msg.content)
                    except Exception:
                        pass
                parts = [
                    types.Part.from_function_call(
                        name=msg.tool_call_id,
                        args=args,
                    )
                ]

            role = self._translate_role(msg.role)
            out.append(types.Content(role=role, parts=parts))

        return out

    def _translate_tools(self, tools: list | None) -> list[types.Tool] | None:
        """Translate DSRT ToolDefinition to Gemini FunctionDeclaration."""
        if not tools:
            return None

        declarations = []
        for t in tools:
            schema = t.parameters.model_dump()
            declarations.append(
                types.FunctionDeclaration(
                    name=t.name,
                    description=t.description,
                    parameters=schema,
                )
            )

        return [types.Tool(function_declarations=declarations)]

    def _translate_finish_reason(self, reason: Any) -> FinishReason:
        """Map Gemini finish reasons to DSRT canonical enum."""
        val = reason.value if hasattr(reason, "value") else reason
        if val in (1, "STOP"):
            return FinishReason.COMPLETED
        elif val in (2, "MAX_TOKENS"):
            return FinishReason.MAX_TOKENS
        elif val in (3, "SAFETY"):
            return FinishReason.CONTENT_FILTER
        return FinishReason.COMPLETED

    def _handle_api_error(self, e: Exception, request_id: str) -> DSRTError:
        """Normalize Gemini errors into DSRT ModelError."""
        if isinstance(e, errors.APIError):
            code = getattr(e, "code", 500)
            message = str(e)

            if code == 429:
                err = ModelError(
                    code=ModelErrorCode.PROVIDER_RATE_LIMITED,
                    message=message,
                    retry_classification=RetryClassification.RETRYABLE_WITH_BACKOFF,
                    request_id=request_id,
                    provider_status_code=code,
                )
            elif code in (401, 403):
                err = ModelError(
                    code=ModelErrorCode.CREDENTIAL_INVALID,
                    message=message,
                    retry_classification=RetryClassification.NOT_RETRYABLE,
                    request_id=request_id,
                    provider_status_code=code,
                )
            elif code in (500, 503, 504):
                err = ModelError(
                    code=ModelErrorCode.PROVIDER_UNAVAILABLE,
                    message=message,
                    retry_classification=RetryClassification.RETRYABLE,
                    request_id=request_id,
                    provider_status_code=code,
                )
            else:
                err = ModelError(
                    code=ModelErrorCode.PROVIDER_INTERNAL_ERROR,
                    message=message,
                    retry_classification=RetryClassification.FALLBACK_ELIGIBLE,
                    request_id=request_id,
                    provider_status_code=code,
                )
        else:
            err = ModelError(
                code=ModelErrorCode.PROVIDER_INTERNAL_ERROR,
                message=str(e),
                retry_classification=RetryClassification.FALLBACK_ELIGIBLE,
                request_id=request_id,
            )

        return DSRTError(err.message, metadata=err.model_dump(), cause=e)

    async def generate(
        self, request: ModelRequest, api_key: str | None = None,
    ) -> ModelResponse:
        client = self._get_client(api_key)

        model_name = "gemini-1.5-pro"
        if request.model_policy and request.model_policy.preferred_models:
            model_name = request.model_policy.preferred_models[0]
        if hasattr(request, "_selected_model_identifier"):
            model_name = getattr(request, "_selected_model_identifier")

        config_kwargs: dict[str, Any] = {}
        if request.temperature is not None:
            config_kwargs["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            config_kwargs["max_output_tokens"] = request.max_output_tokens
        if request.top_p is not None:
            config_kwargs["top_p"] = request.top_p

        if request.system_context:
            config_kwargs["system_instruction"] = json.dumps(request.system_context)

        if request.tools:
            config_kwargs["tools"] = self._translate_tools(request.tools)

        if request.response_schema:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = request.response_schema
        elif request.response_mime_type == "application/json":
            config_kwargs["response_mime_type"] = "application/json"

        config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None
        contents = self._translate_messages(request.messages)

        try:
            resp = await client.aio.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
        except Exception as e:
            raise self._handle_api_error(e, request.request_id) from e

        if not resp.candidates:
            raise DSRTError("Gemini returned zero candidates.")

        candidate = resp.candidates[0]
        content = candidate.content

        output_text = ""
        tool_calls = []
        structured_out = None

        if content and content.parts:
            for part in content.parts:
                if part.text:
                    output_text += part.text
                if part.function_call:
                    args = {}
                    if part.function_call.args:
                        args = part.function_call.args
                        if hasattr(args, "model_dump"):
                            args = args.model_dump()
                        elif isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                pass

                    tool_calls.append(
                        ToolCall(
                            id=part.function_call.name,
                            name=part.function_call.name,
                            arguments=args,
                            raw_arguments_text=json.dumps(args),
                        )
                    )

        if request.response_schema and output_text:
            try:
                structured_out = json.loads(output_text)
            except json.JSONDecodeError:
                pass

        usage = Usage()
        if resp.usage_metadata:
            usage = Usage(
                input_tokens=resp.usage_metadata.prompt_token_count,
                output_tokens=resp.usage_metadata.candidates_token_count,
                total_tokens=resp.usage_metadata.total_token_count,
            )

        return ModelResponse(
            request_id=request.request_id,
            model_id="mdl_dynamic",
            provider_id=self.PROVIDER_ID,
            model_identifier=resp.model_version or model_name,
            output=output_text if output_text else None,
            structured_output=structured_out,
            tool_calls=tool_calls,
            finish_reason=self._translate_finish_reason(candidate.finish_reason),
            usage=usage,
            latency_ms=0,
            created_at=datetime.now(timezone.utc),
            attempt=request.attempt,
        )

    async def stream(
        self, request: ModelRequest, api_key: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        raise NotImplementedError("Streaming is stubbed in C2.4")

    async def count_tokens(
        self, request: TokenCountRequest, model_identifier: str,
    ) -> TokenCountResponse:
        text = str(request.system_context or "")
        for m in request.messages:
            text += str(m.content)
        estimate = len(text) // 4

        return TokenCountResponse(
            input_tokens=estimate,
            total_tokens=estimate,
            model_identifier=model_identifier,
            is_estimate=True,
        )

    async def embed(
        self, request: "EmbeddingRequest", api_key: str | None = None,
    ) -> "EmbeddingResponse":
        """Generate embeddings via Google Embedding API (stub for C4.5)."""
        from core.providers.base.adapter import EmbeddingResponse

        # Google embedding implementation arrives when needed.
        # For now, raise NotImplementedError so the system falls back
        # to the configured embedding provider.
        raise NotImplementedError(
            "Google embedding API integration is not yet implemented. "
            "Use OpenAI or another provider for embeddings."
        )

    async def check_health(self) -> ProviderHealth:
        return ProviderHealth(
            provider_id=self.PROVIDER_ID,
            status=ProviderHealthStatus.HEALTHY,
            observed_at=datetime.now(timezone.utc),
        )