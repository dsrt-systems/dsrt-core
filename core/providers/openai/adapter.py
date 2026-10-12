"""
OpenAI Provider Adapter.

Translates DSRT canonical requests into OpenAI Chat Completion payloads.
Handles text, image, tool calling, structured output, and embeddings.
Uses lazy imports to prevent application crashes if the openai SDK is 
blocked by OS security policies (e.g., Windows Smart App Control).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, AsyncIterator

from core.api.errors.exceptions import DSRTError
from core.providers.base.adapter import EmbeddingRequest, EmbeddingResponse, ModelProviderAdapter
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

if TYPE_CHECKING:
    import openai
    from openai import AsyncOpenAI


class OpenAIAdapter(ModelProviderAdapter):
    """OpenAI API implementation of the DSRT Model Provider Adapter."""

    PROVIDER_ID = "prv_openai_internal"  # Will be overridden by DB state in C2.6
    PROVIDER_SLUG = "openai"

    def __init__(self, default_api_key: str | None = None) -> None:
        self._default_api_key = default_api_key

    def _get_client(self, api_key: str | None) -> AsyncOpenAI:
        """Initialize transient client to prevent key leakage across requests."""
        # LAZY IMPORT: Prevents crash if openai SDK is blocked by OS policies
        from openai import AsyncOpenAI 
        
        key = api_key or self._default_api_key
        if not key:
            raise ValueError(
                "OpenAI API key missing. Must provide BYOK or set managed default."
            )
        return AsyncOpenAI(api_key=key, max_retries=0)  # DSRT handles retries

    # -----------------------------------------------------------------------
    # Payload Translation
    # -----------------------------------------------------------------------

    def _translate_messages(
        self, messages: list[ModelMessage], system_context: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        """Translate DSRT messages to OpenAI messages."""
        out: list[dict[str, Any]] = []

        if system_context:
            out.append(
                {
                    "role": "system",
                    "content": json.dumps(system_context, indent=2),
                }
            )

        for msg in messages:
            o_msg: dict[str, Any] = {"role": msg.role.value}
            
            if msg.role == MessageRole.TOOL:
                o_msg["tool_call_id"] = msg.tool_call_id
                o_msg["content"] = str(msg.content)
            elif isinstance(msg.content, str):
                o_msg["content"] = msg.content
            elif isinstance(msg.content, list):
                parts = []
                for part in msg.content:
                    if part.type == MessageContentType.TEXT:
                        parts.append({"type": "text", "text": part.text})
                    elif part.type == MessageContentType.IMAGE_URL:
                        parts.append(
                            {"type": "image_url", "image_url": {"url": part.image_url}}
                        )
                    elif part.type == MessageContentType.IMAGE_BYTES:
                        parts.append(
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{part.image_mime_type};base64,{part.image_bytes_base64}"
                                },
                            }
                        )
                o_msg["content"] = parts

            if msg.name:
                o_msg["name"] = msg.name

            out.append(o_msg)

        return out

    def _translate_tools(self, tools: list | None) -> list[dict[str, Any]] | None:
        """Translate DSRT ToolDefinition to OpenAI tool specification."""
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters.model_dump(),
                },
            }
            for t in tools
        ]

    def _translate_tool_choice(self, choice: str | None) -> Any:
        """Translate DSRT tool_choice hint."""
        if choice in ("auto", "none", "required", None):
            return choice
        return {"type": "function", "function": {"name": choice}}

    def _translate_finish_reason(self, reason: str | None) -> FinishReason:
        """Map OpenAI finish reasons to DSRT canonical enum."""
        mapping = {
            "stop": FinishReason.COMPLETED,
            "length": FinishReason.MAX_TOKENS,
            "tool_calls": FinishReason.TOOL_CALLS,
            "content_filter": FinishReason.CONTENT_FILTER,
        }
        return mapping.get(reason or "stop", FinishReason.COMPLETED)

    def _handle_api_error(self, e: Exception, request_id: str) -> DSRTError:
        """Normalize OpenAI errors into DSRT ModelError."""
        # LAZY IMPORT
        import openai
        
        if isinstance(e, openai.RateLimitError):
            err = ModelError(
                code=ModelErrorCode.PROVIDER_RATE_LIMITED,
                message=str(e),
                retry_classification=RetryClassification.RETRYABLE_WITH_BACKOFF,
                request_id=request_id,
                provider_status_code=e.status_code,
            )
        elif isinstance(e, openai.APITimeoutError):
            err = ModelError(
                code=ModelErrorCode.PROVIDER_TIMEOUT,
                message="OpenAI timeout",
                retry_classification=RetryClassification.RETRYABLE,
                request_id=request_id,
            )
        elif isinstance(e, openai.AuthenticationError):
            err = ModelError(
                code=ModelErrorCode.CREDENTIAL_INVALID,
                message="OpenAI API key invalid or unauthorized",
                retry_classification=RetryClassification.NOT_RETRYABLE,
                request_id=request_id,
                provider_status_code=e.status_code,
            )
        else:
            err = ModelError(
                code=ModelErrorCode.PROVIDER_INTERNAL_ERROR,
                message=str(e),
                retry_classification=RetryClassification.FALLBACK_ELIGIBLE,
                request_id=request_id,
            )
        
        return DSRTError(err.message, metadata=err.model_dump(), cause=e)

    # -----------------------------------------------------------------------
    # Interface Implementation
    # -----------------------------------------------------------------------

    async def generate(
        self, request: ModelRequest, api_key: str | None = None,
    ) -> ModelResponse:
        client = self._get_client(api_key)

        kwargs: dict[str, Any] = {
            "model": request.model_policy.preferred_models[0] if request.model_policy and request.model_policy.preferred_models else "gpt-4o",
            "messages": self._translate_messages(request.messages, request.system_context),
        }

        if hasattr(request, "_selected_model_identifier"):
            kwargs["model"] = getattr(request, "_selected_model_identifier")

        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            kwargs["max_tokens"] = request.max_output_tokens
        if request.tools:
            kwargs["tools"] = self._translate_tools(request.tools)
            if request.tool_choice:
                kwargs["tool_choice"] = self._translate_tool_choice(request.tool_choice)
        if request.response_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_output",
                    "strict": True,
                    "schema": request.response_schema,
                },
            }
        elif request.response_mime_type == "application/json":
            kwargs["response_format"] = {"type": "json_object"}

        try:
            resp = await client.chat.completions.create(**kwargs)
        except Exception as e:
            raise self._handle_api_error(e, request.request_id) from e

        choice = resp.choices[0]
        msg = choice.message

        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                args = {}
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    pass
                
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                        raw_arguments_text=tc.function.arguments,
                    )
                )

        structured_out = None
        if request.response_schema and msg.content:
            try:
                structured_out = json.loads(msg.content)
            except json.JSONDecodeError:
                pass

        usage = Usage()
        if resp.usage:
            usage = Usage(
                input_tokens=resp.usage.prompt_tokens,
                output_tokens=resp.usage.completion_tokens,
                total_tokens=resp.usage.total_tokens,
            )

        return ModelResponse(
            request_id=request.request_id,
            model_id="mdl_dynamic",
            provider_id=self.PROVIDER_ID,
            model_identifier=resp.model,
            output=msg.content,
            structured_output=structured_out,
            tool_calls=tool_calls,
            finish_reason=self._translate_finish_reason(choice.finish_reason),
            usage=usage,
            latency_ms=0,
            created_at=datetime.now(timezone.utc),
            attempt=request.attempt,
        )

    async def stream(
        self, request: ModelRequest, api_key: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        raise NotImplementedError("Streaming is stubbed in C2.3")

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
        self, request: EmbeddingRequest, api_key: str | None = None,
    ) -> EmbeddingResponse:
        """Generate embeddings via OpenAI Embeddings API."""
        client = self._get_client(api_key)

        kwargs: dict[str, Any] = {
            "model": request.model_identifier,
            "input": request.texts,
        }
        if request.dimensions is not None:
            kwargs["dimensions"] = request.dimensions

        try:
            resp = await client.embeddings.create(**kwargs)
        except Exception as e:
            raise self._handle_api_error(e, "embed_request") from e

        embeddings = [item.embedding for item in resp.data]
        dimensions = len(embeddings[0]) if embeddings else 0
        total_tokens = resp.usage.total_tokens if resp.usage else 0

        return EmbeddingResponse(
            embeddings=embeddings,
            model_identifier=request.model_identifier,
            dimensions=dimensions,
            total_tokens=total_tokens,
        )

    async def check_health(self) -> ProviderHealth:
        return ProviderHealth(
            provider_id=self.PROVIDER_ID,
            status=ProviderHealthStatus.HEALTHY,
            observed_at=datetime.now(timezone.utc),
        )