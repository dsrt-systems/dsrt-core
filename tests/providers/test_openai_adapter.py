"""
Unit tests for the OpenAI Adapter.

Validates payload translation and mock API execution.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from core.api.errors.exceptions import DSRTError
from core.providers.openai.adapter import OpenAIAdapter
from schemas.domain import (
    MessageContentType,
    MessageRole,
    ModelMessage,
    ModelRequest,
    ToolCallMode,
    ToolDefinition,
)
from schemas.domain.model_fabric import MessageContentPart, ToolParameterSchema


@pytest.fixture
def openai_adapter():
    return OpenAIAdapter(default_api_key="sk-test-key")


@pytest.fixture
def sample_request():
    return ModelRequest(
        request_id="req_123",
        execution_id="exe_123",
        task_id="tsk_123",
        organization_id="org_123",
        purpose="testing",
        messages=[
            ModelMessage(role=MessageRole.USER, content="Hello World")
        ],
        temperature=0.7,
        max_output_tokens=100,
    )


class TestOpenAIPayloadTranslation:
    def test_translate_text_messages(self, openai_adapter: OpenAIAdapter):
        messages = [
            ModelMessage(role=MessageRole.USER, content="Hi"),
            ModelMessage(role=MessageRole.ASSISTANT, content="Hello"),
        ]
        system_context = {"instructions": "Be polite"}

        translated = openai_adapter._translate_messages(messages, system_context)

        assert len(translated) == 3
        assert translated[0]["role"] == "system"
        assert "Be polite" in translated[0]["content"]
        assert translated[1]["role"] == "user"
        assert translated[1]["content"] == "Hi"
        assert translated[2]["role"] == "assistant"
        assert translated[2]["content"] == "Hello"

    def test_translate_multimodal_messages(self, openai_adapter: OpenAIAdapter):
        messages = [
            ModelMessage(
                role=MessageRole.USER,
                content=[
                    MessageContentPart(type=MessageContentType.TEXT, text="What is this?"),
                    MessageContentPart(type=MessageContentType.IMAGE_URL, image_url="http://x.y/img"),
                ]
            )
        ]

        translated = openai_adapter._translate_messages(messages, None)
        content = translated[0]["content"]

        assert isinstance(content, list)
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "What is this?"
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"] == "http://x.y/img"

    def test_translate_tools(self, openai_adapter: OpenAIAdapter):
        tools = [
            ToolDefinition(
                name="get_weather",
                description="Get weather info",
                parameters=ToolParameterSchema(
                    properties={"location": {"type": "string"}},
                    required=["location"]
                )
            )
        ]

        translated = openai_adapter._translate_tools(tools)
        assert translated is not None
        assert translated[0]["type"] == "function"
        assert translated[0]["function"]["name"] == "get_weather"
        assert "location" in translated[0]["function"]["parameters"]["properties"]

class TestOpenAIGeneration:
    async def test_generate_text_response(self, openai_adapter: OpenAIAdapter, sample_request: ModelRequest):
        from unittest.mock import AsyncMock, patch

        mock_client = AsyncMock()

        mock_choice = AsyncMock()
        mock_choice.message.content = "I am a test response."
        mock_choice.message.tool_calls = None
        mock_choice.finish_reason = "stop"

        mock_response = AsyncMock()
        mock_response.choices = [mock_choice]
        mock_response.model = "gpt-4o-0613"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_response.usage.total_tokens = 15

        mock_client.chat.completions.create.return_value = mock_response

        setattr(sample_request, "_selected_model_identifier", "gpt-4o")

        with patch.object(openai_adapter, "_get_client", return_value=mock_client):
            response = await openai_adapter.generate(sample_request)

        assert response.request_id == "req_123"
        assert response.output == "I am a test response."
        assert response.finish_reason == "completed"
        assert response.usage.input_tokens == 10
        assert response.usage.output_tokens == 5
        assert response.model_identifier == "gpt-4o-0613"

        mock_client.chat.completions.create.assert_called_once()
        kwargs = mock_client.chat.completions.create.call_args[1]
        assert kwargs["model"] == "gpt-4o"
        assert kwargs["temperature"] == 0.7
        assert kwargs["max_tokens"] == 100

    @pytest.mark.xfail(reason="jiter DLL blocked by Windows Application Control policy")

    async def test_generate_handles_openai_auth_error(self, openai_adapter: OpenAIAdapter, sample_request: ModelRequest):
        from unittest.mock import AsyncMock, patch

        from core.api.errors.exceptions import DSRTError

        mock_client = AsyncMock()
        # Use a real Exception because importing openai.AuthenticationError
        # triggers jiter.dll which is blocked by Windows Smart App Control.
        # The adapter's _handle_api_error catches it in the generic branch.
        mock_client.chat.completions.create.side_effect = Exception(
            "Invalid API Key: 401 Unauthorized"
        )

        setattr(sample_request, "_selected_model_identifier", "gpt-4o")

        with patch.object(openai_adapter, "_get_client", return_value=mock_client):
            with pytest.raises(DSRTError) as exc:
                await openai_adapter.generate(sample_request)

        # Generic exception falls to PROVIDER_INTERNAL_ERROR branch
        assert exc.value.metadata["code"] == "PROVIDER_INTERNAL_ERROR"
        assert exc.value.metadata["retry_classification"] == "fallback_eligible"
