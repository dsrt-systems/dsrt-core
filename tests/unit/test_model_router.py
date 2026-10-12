"""
Unit tests for the Model Router constraint resolution engine.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.api.errors.exceptions import DSRTError
from core.models.router import ModelRouter
from schemas.domain import (
    MessageRole,
    ModelMessage,
    ModelPolicy,
    ModelRequest,
    RoutingReasonCode,
    ToolDefinition,
)


@pytest.fixture
def mock_provider_repo():
    repo = MagicMock()
    
    # Use a valid datetime to satisfy Pydantic validation
    now = datetime.now(timezone.utc)
    
    # Mock Provider
    provider = MagicMock()
    provider.id = "prv_openai"
    provider.slug = "openai"
    provider.status = "active"
    provider.name = "OpenAI"
    provider.provider_type = "cloud"
    provider.description = ""
    provider.configuration = {}
    provider.created_at = now
    provider.updated_at = now

    repo.list_providers = AsyncMock(return_value=[provider])

    # Mock Models
    m1 = MagicMock()
    m1.id = "mdl_gpt4"
    m1.provider_id = "prv_openai"
    m1.slug = "gpt-4"
    m1.name = "GPT-4"
    m1.model_identifier = "gpt-4-0613"
    m1.version = "1.0"
    m1.status = "active"
    m1.created_at = now
    m1.updated_at = now
    m1.capabilities = {
        "capabilities": {"text_generation": True, "tool_calling": True, "vision": True, "structured_output": True},
        "context_config": {"max_input_tokens": 128000, "max_output_tokens": 4096},
        "pricing_config": {"input_cost_per_m": "10.0", "output_cost_per_m": "30.0"},
    }

    m2 = MagicMock()
    m2.id = "mdl_mini"
    m2.provider_id = "prv_openai"
    m2.slug = "gpt-4-mini"
    m2.name = "GPT-4 Mini"
    m2.model_identifier = "gpt-4-mini"
    m2.version = "1.0"
    m2.status = "active"
    m2.created_at = now
    m2.updated_at = now
    m2.capabilities = {
        "capabilities": {"text_generation": True, "tool_calling": False, "vision": False, "structured_output": True},
        "context_config": {"max_input_tokens": 16000, "max_output_tokens": 2048},
        "pricing_config": {"input_cost_per_m": "1.0", "output_cost_per_m": "3.0"},
    }

    repo.list_models = AsyncMock(return_value=[m1, m2])
    return repo


@pytest.fixture
def sample_request():
    return ModelRequest(
        request_id="req_100",
        execution_id="exe_100",
        task_id="tsk_100",
        organization_id="org_100",
        purpose="testing",
        messages=[ModelMessage(role=MessageRole.USER, content="Hello")],
    )


class TestModelRouter:
    async def test_route_selects_cheapest_when_preferred(self, mock_provider_repo, sample_request):
        router = ModelRouter(mock_provider_repo)
        policy = ModelPolicy(prefer_lower_cost=True)
        
        selection = await router.route(sample_request, policy=policy)
        
        assert selection.selected_model.slug == "gpt-4-mini"
        assert selection.decision.selected_model_id == "mdl_mini"

    async def test_route_filters_out_models_lacking_tool_calling(self, mock_provider_repo, sample_request):
        router = ModelRouter(mock_provider_repo)
        sample_request.tools = [ToolDefinition(name="search", description="web search")]
        
        selection = await router.route(sample_request)
        
        # gpt-4-mini does not support tool calling in our mock, so gpt-4 must be selected
        assert selection.selected_model.slug == "gpt-4"
        assert len(selection.decision.rejected_candidates) == 1
        assert selection.decision.rejected_candidates[0].model_id == "mdl_mini"
        assert RoutingReasonCode.CAPABILITY_MISMATCH in selection.decision.rejected_candidates[0].reason_codes

    async def test_route_filters_blocked_models(self, mock_provider_repo, sample_request):
        router = ModelRouter(mock_provider_repo)
        policy = ModelPolicy(blocked_models=["gpt-4"])
        
        selection = await router.route(sample_request, policy=policy)
        assert selection.selected_model.slug == "gpt-4-mini"

    async def test_route_raises_when_no_candidates_eligible(self, mock_provider_repo, sample_request):
        router = ModelRouter(mock_provider_repo)
        policy = ModelPolicy(blocked_models=["gpt-4", "gpt-4-mini"])
        
        with pytest.raises(DSRTError, match="No eligible model candidates"):
            await router.route(sample_request, policy=policy)