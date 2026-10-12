"""
Unit tests for the Google Gemini Adapter.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from google.genai import errors

from core.api.errors.exceptions import DSRTError
from core.providers.google.adapter import GoogleAdapter
from schemas.domain import (
    MessageRole,
    ModelMessage,
    ModelRequest,
    ToolDefinition,
)
from schemas.domain.model_fabric import ToolParameterSchema


@pytest.fixture
def google_adapter():
    return GoogleAdapter(default_api_key="AIzaSyTestKey")


@pytest.fixture
def sample_request():
    return ModelRequest(
        request_id="req_123",
        execution_id="exe_123",
        task_id="tsk_123",
        organization_id="org_123",
        purpose="testing",
        messages=[ModelMessage(role=MessageRole.USER, content="Hello World")],
        temperature=0.7,
        max_output_tokens=100,
    )


class TestGooglePayloadTranslation:
    def test_translate_text_messages(self, google_adapter: GoogleAdapter):
        messages = [
            ModelMessage(role=MessageRole.USER, content="Hi"),
            ModelMessage(role=MessageRole.ASSISTANT, content="Hello"),
        ]

        translated = google_adapter._translate_messages(messages)

        assert len(translated) == 2
        assert translated[0].role == "user"
        assert translated[0].parts[0].text == "Hi"
        assert translated[1].role == "model"
        assert translated[1].parts[0].text == "Hello"

    def test_translate_tools(self, google_adapter: GoogleAdapter):
        tools = [
            ToolDefinition(
                name="get_weather",
                description="Get weather info",
                parameters=ToolParameterSchema(
                    properties={"location": {"type": "string"}},
                    required=["location"],
                ),
            )
        ]

        translated = google_adapter._translate_tools(tools)
        assert translated is not None
        assert len(translated) == 1
        assert len(translated[0].function_declarations) == 1
        assert translated[0].function_declarations[0].name == "get_weather"
        # In google-genai 2.27.0, parameters is a types.Schema object with attributes
        params = translated[0].function_declarations[0].parameters
        assert "location" in params.properties


class TestGoogleGeneration:
    @patch("core.providers.google.adapter.genai.Client")
    async def test_generate_text_response(
        self, mock_client_class, google_adapter: GoogleAdapter, sample_request: ModelRequest
    ):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.aio = AsyncMock()

        mock_part = MagicMock()
        mock_part.text = "I am Gemini."
        mock_part.function_call = None

        mock_content = MagicMock()
        mock_content.parts = [mock_part]

        mock_candidate = MagicMock()
        mock_candidate.content = mock_content
        mock_candidate.finish_reason = 1

        mock_usage = MagicMock()
        mock_usage.prompt_token_count = 5
        mock_usage.candidates_token_count = 10
        mock_usage.total_token_count = 15

        mock_resp = MagicMock()
        mock_resp.candidates = [mock_candidate]
        mock_resp.usage_metadata = mock_usage
        mock_resp.model_version = "gemini-1.5-pro-001"

        mock_client.aio.models.generate_content.return_value = mock_resp

        setattr(sample_request, "_selected_model_identifier", "gemini-1.5-pro")
        response = await google_adapter.generate(sample_request)

        assert response.request_id == "req_123"
        assert response.output == "I am Gemini."
        assert response.finish_reason == "completed"
        assert response.usage.input_tokens == 5
        assert response.usage.output_tokens == 10

    @patch("core.providers.google.adapter.genai.Client")
    async def test_generate_handles_auth_error(
        self, mock_client_class, google_adapter: GoogleAdapter, sample_request: ModelRequest
    ):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.aio = AsyncMock()

        # errors.APIError takes (code, message) positionally in google-genai 2.27.0
        err = errors.APIError(403, "API key not valid")
        mock_client.aio.models.generate_content.side_effect = err

        with pytest.raises(DSRTError) as exc:
            await google_adapter.generate(sample_request)

        assert exc.value.metadata["code"] == "CREDENTIAL_INVALID"
        assert exc.value.metadata["retry_classification"] == "not_retryable"