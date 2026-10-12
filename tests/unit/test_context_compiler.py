"""
Unit tests for the Context Compiler (C2.7).

Validates token budgeting, priority filtering, truncation, and provenance tracking.
"""

from __future__ import annotations

import pytest

from core.models.context.compiler import ContextCompiler
from schemas.domain.context_compiler import ContextBudget
from schemas.domain.enums import MessageRole
from schemas.domain.model_fabric import ModelMessage
from schemas.domain.provider import ModelContextConfig
from sdk.agent import SDKAgentContext, SDKMemoryRecord, SDKToolResult


@pytest.fixture
def base_agent_context():
    return SDKAgentContext(
        execution_id="exe_1",
        task_id="tsk_1",
        organization_id="org_1",
        user_id="usr_1",
        agent_slug="research",
        agent_version="1.0",
        objective="Analyze data.",
        working_state={"step": 1, "findings": ["A", "B"]},
    )


@pytest.fixture
def ample_model_config():
    return ModelContextConfig(
        max_input_tokens=100000,
        max_output_tokens=4000,
    )


@pytest.fixture
def constrained_model_config():
    return ModelContextConfig(
        max_input_tokens=100,  # Extremely small for testing truncation
        max_output_tokens=20,
    )


class TestContextCompiler:
    def test_compiles_all_state_within_budget(
        self, base_agent_context, ample_model_config
    ):
        compiler = ContextCompiler()
        
        memories = [SDKMemoryRecord(id="mem_1", memory_type="semantic", content="Important fact.")]
        tools = [SDKToolResult(tool_slug="web", status="SUCCESS", output="Search results here.")]
        history = [ModelMessage(role=MessageRole.USER, content="Hello")]
        
        compiled = compiler.compile(
            agent_context=base_agent_context,
            model_config=ample_model_config,
            memories=memories,
            tool_results=tools,
            conversation_history=history,
        )
        
        assert compiled.state_dropped is False
        assert compiled.output_budget_reserved == 4000
        assert compiled.total_tokens > 0
        
        # Check Provenance
        assert len(compiled.provenance) == 3
        types = [p.source_type for p in compiled.provenance]
        assert "working_state" in types
        assert "tool_result" in types
        assert "memory" in types

    def test_drops_memory_and_history_when_budget_constrained(
        self, base_agent_context, constrained_model_config
    ):
        compiler = ContextCompiler()
        
        # Giant payload that will blow out the 100 token budget
        memories = [SDKMemoryRecord(id="mem_1", memory_type="semantic", content="x" * 1000)]
        history = [ModelMessage(role=MessageRole.USER, content="y" * 1000)]
        
        compiled = compiler.compile(
            agent_context=base_agent_context,
            model_config=constrained_model_config,
            memories=memories,
            conversation_history=history,
        )
        
        # Working state fits, but memory and history should be dropped
        assert compiled.state_dropped is True
        
        types = [p.source_type for p in compiled.provenance]
        assert "working_state" in types
        assert "memory" not in types

    def test_truncates_large_tool_result(
        self, base_agent_context, constrained_model_config
    ):
        compiler = ContextCompiler()
        
        tools = [SDKToolResult(tool_slug="web", status="SUCCESS", output="x" * 1000)]
        
        compiled = compiler.compile(
            agent_context=base_agent_context,
            model_config=constrained_model_config,
            tool_results=tools,
        )
        
        assert compiled.state_dropped is True
        
        # Find tool provenance
        tool_prov = next((p for p in compiled.provenance if p.source_type == "tool_result"), None)
        assert tool_prov is not None
        assert tool_prov.was_truncated is True
        assert tool_prov.included_size_tokens < tool_prov.original_size_tokens

    def test_raises_if_system_prompt_exceeds_budget(
        self, base_agent_context
    ):
        compiler = ContextCompiler()
        
        # Config where max_input is smaller than reserved output
        impossible_config = ModelContextConfig(
            max_input_tokens=10,
            max_output_tokens=20,
        )
        
        with pytest.raises(ValueError, match="Context budget exceeded"):
            compiler.compile(
                agent_context=base_agent_context,
                model_config=impossible_config,
            )