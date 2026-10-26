"""
C10.4 Amplification Runtime Tests (Isolated)
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from schemas.domain.enums import (
    C10ExecutionStatus,
    ExecutionMode,
    ExecutionProtocol,
    AmplificationStrategy,
    StepKind,
    StepStatus,
)
from schemas.domain.execution_c10 import ExecutionConfigurationCreate, ExecutionTrace
from core.execution.amplified.adapter import AmplifiedSubsystemAdapter
from core.execution.amplified.strategies.implementations import get_strategy_implementation
from core.execution.amplified.pipeline import AmplifiedPipeline
from core.execution.protocols.amplified import AmplifiedExecutionProtocol

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_session():
    return AsyncMock()


async def test_subsystem_adapter():
    adapter = AmplifiedSubsystemAdapter()

    docs = await adapter.retrieve_context("Test")
    assert len(docs) == 1

    plan = await adapter.generate_plan("Test", docs)
    assert "steps" in plan

    result = await adapter.execute_tool_grounded("Test", plan, ["test_tool"])
    assert "content" in result
    assert result["usage"]["total_tokens"] > 0
    assert result["duration_ms"] >= 0


async def test_strategies_execution():
    adapter = AmplifiedSubsystemAdapter()
    state = {}
    payload = {"prompt": "Test Prompt"}

    retrieval = get_strategy_implementation(AmplificationStrategy.CONTEXT_RETRIEVAL, adapter)
    ret_res = await retrieval.execute(payload, state)
    assert "retrieved_context" in state
    assert ret_res["documents_retrieved"] == 1

    planning = get_strategy_implementation(AmplificationStrategy.PLANNING, adapter)
    plan_res = await planning.execute(payload, state)
    assert "execution_plan" in state
    assert plan_res["steps_planned"] > 0

    tool = get_strategy_implementation(AmplificationStrategy.TOOL_GROUNDED, adapter)
    tool_res = await tool.execute(payload, state)
    assert "model_output" in state
    assert tool_res["usage"]["total_tokens"] > 0


async def test_amplified_pipeline(mock_session):
    pipeline = AmplifiedPipeline(mock_session)

    mock_step_orm = MagicMock()
    mock_step_orm.id = "step_1"
    pipeline.step_repo.create_step = AsyncMock(return_value=mock_step_orm)
    pipeline.step_repo.update_step_status = AsyncMock()

    strategies = [AmplificationStrategy.CONTEXT_RETRIEVAL, AmplificationStrategy.TOOL_GROUNDED]

    result = await pipeline.execute_pipeline(
        trace_id="trace_1",
        strategies=strategies,
        payload={"prompt": "Do work"},
    )

    assert "content" in result
    assert result["metrics"]["steps_executed"] == 2
    assert pipeline.step_repo.create_step.call_count == 2
    assert pipeline.step_repo.update_step_status.call_count == 2

    # Verify create_step called with domain signature expected by fixed repository.
    first_call = pipeline.step_repo.create_step.await_args_list[0].kwargs
    assert first_call["trace_id"] == "trace_1"
    assert first_call["step_number"] == 1
    assert first_call["kind"] == StepKind.AMPLIFICATION_STAGE


async def test_amplified_protocol(mock_session):
    protocol = AmplifiedExecutionProtocol(mock_session)

    now = datetime.now(timezone.utc)

    # Build a realistic ORM-shaped object; ExecutionTrace mapper must accept it.
    mock_trace_orm = MagicMock()
    mock_trace_orm.id = "trace_123"
    mock_trace_orm.organization_id = "org_1"
    mock_trace_orm.configuration_id = "config_1"
    mock_trace_orm.status = C10ExecutionStatus.SUCCEEDED.value
    mock_trace_orm.protocol = ExecutionProtocol.AMPLIFIED.value
    mock_trace_orm.mode = ExecutionMode.WORK.value
    mock_trace_orm.total_cost_usd = 0.0003
    mock_trace_orm.total_input_tokens = 50
    mock_trace_orm.total_output_tokens = 100
    mock_trace_orm.total_duration_ms = 500
    mock_trace_orm.step_count = 1
    mock_trace_orm.error_code = None
    mock_trace_orm.error_message = None
    mock_trace_orm.error_metadata = {
        "pricing_snapshot_id": "snap_123",
        "metadata_json": {},
        "claims_count": 0,
    }
    mock_trace_orm.created_at = now
    mock_trace_orm.updated_at = now
    mock_trace_orm.started_at = now
    mock_trace_orm.completed_at = now
    mock_trace_orm.admitted_at = None

    protocol.runtime.trace_repo.update_status = AsyncMock(return_value=mock_trace_orm)
    protocol.runtime.trace_repo.update_metrics = AsyncMock(return_value=mock_trace_orm)

    # Let the real pipeline run, but stub DB step writes.
    mock_step = MagicMock()
    mock_step.id = "step_amp_1"
    protocol.runtime.pipeline.step_repo.create_step = AsyncMock(return_value=mock_step)
    protocol.runtime.pipeline.step_repo.update_step_status = AsyncMock(return_value=mock_step)

    config = ExecutionConfigurationCreate(
        organization_id="org_1",
        protocol=ExecutionProtocol.AMPLIFIED,
        mode=ExecutionMode.WORK,
        model_identifier="test-model",
        amplification_strategies=[AmplificationStrategy.VERIFICATION.value],
    )

    trace = await protocol.execute("trace_123", config, {"prompt": "Test"})

    assert isinstance(trace, ExecutionTrace)
    assert trace.status == C10ExecutionStatus.SUCCEEDED
    assert trace.protocol == ExecutionProtocol.AMPLIFIED
    assert trace.total_tokens == 150  # 50 + 100 mapped from ORM
    assert trace.pricing_snapshot_id == "snap_123"

    protocol.runtime.trace_repo.update_metrics.assert_called_once()
    protocol.runtime.trace_repo.update_status.assert_called_once()
    protocol.runtime.pipeline.step_repo.create_step.assert_called()