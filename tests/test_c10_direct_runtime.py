"""
C10.3 Direct Execution Runtime Tests (Isolated)
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from schemas.domain.enums import C10ExecutionStatus, ExecutionMode, ExecutionProtocol, StepKind, StepStatus
from schemas.domain.execution_c10 import ExecutionConfigurationCreate
from core.execution.direct.context_binder import DirectContextBinder
from core.execution.direct.adapter import DirectExecutionAdapter
from core.execution.direct.step_runner import StepRunner
from core.execution.direct.runtime import DirectRuntime
from core.execution.protocols.direct import DirectExecutionProtocol

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_session():
    return AsyncMock()


async def test_direct_context_binder():
    binder = DirectContextBinder()
    config = ExecutionConfigurationCreate(
        organization_id="org_test",
        protocol=ExecutionProtocol.DIRECT,
        mode=ExecutionMode.WORK,
        model_identifier="gpt-4o",
        model_provider="openai",
        system_prompt="System Prompt",
    )
    payload = {"prompt": "Hello AI"}

    bound = binder.bind("trace_123", config, payload)
    
    assert bound.trace_id == "trace_123"
    assert bound.prompt == "Hello AI"
    assert bound.system_prompt == "System Prompt"
    assert bound.model_identifier == "gpt-4o"
    assert bound.provider == "openai"


async def test_direct_adapter():
    adapter = DirectExecutionAdapter()
    context = MagicMock()
    context.prompt = "Write a python function"
    context.model_identifier = "gpt-4"
    context.provider = "openai"

    result = await adapter.invoke_model(context)
    
    assert "content" in result
    assert result["model"] == "gpt-4"
    assert result["provider"] == "openai"
    assert result["usage"]["total_tokens"] > 0
    assert result["duration_ms"] >= 0  # Changed to >= because tests can run in 0.0ms


async def test_step_runner(mock_session):
    runner = StepRunner(mock_session)
    
    mock_step_orm = MagicMock()
    mock_step_orm.id = "step_123"
    runner.step_repo.create_step = AsyncMock(return_value=mock_step_orm)
    runner.step_repo.update_step_status = AsyncMock()

    async def mock_work():
        return {"output": "success", "usage": {"total_tokens": 100}, "duration_ms": 500}

    result = await runner.run_step(
        trace_id="trace_123",
        step_number=1,
        kind=StepKind.MODEL_CALL,
        name="test_step",
        input_data={"input": "test"},
        execute_fn=mock_work,
    )

    assert result["output"] == "success"
    runner.step_repo.create_step.assert_called_once()
    runner.step_repo.update_step_status.assert_called_once_with(
        step_id="step_123",
        status=StepStatus.SUCCEEDED,
        output_data=result,
        duration_ms=500,
        cost_usd=0.0002,
        tokens_used=100,
    )


async def test_direct_runtime_and_protocol(mock_session):
    protocol = DirectExecutionProtocol(mock_session)
    
    # Properly mock the ORM object so Pydantic strictly validates it
    now = datetime.now(timezone.utc)
    mock_trace_orm = MagicMock()
    mock_trace_orm.id = "trace_123"
    mock_trace_orm.organization_id = "org_1"
    mock_trace_orm.configuration_id = "config_1"
    mock_trace_orm.status = C10ExecutionStatus.SUCCEEDED.value
    mock_trace_orm.protocol = ExecutionProtocol.DIRECT.value
    mock_trace_orm.mode = ExecutionMode.WORK.value
    mock_trace_orm.pricing_snapshot_id = "snap_123"
    mock_trace_orm.total_cost = 0.0
    mock_trace_orm.total_tokens = 100
    mock_trace_orm.duration_ms = 1000.0
    mock_trace_orm.total_steps = 2
    mock_trace_orm.claims_count = 0
    mock_trace_orm.error_code = None
    mock_trace_orm.error_message = None
    mock_trace_orm.metadata_json = {}
    mock_trace_orm.created_at = now
    mock_trace_orm.updated_at = now
    mock_trace_orm.admitted_at = now
    mock_trace_orm.started_at = now
    mock_trace_orm.completed_at = now

    protocol.runtime.trace_repo.update_status = AsyncMock(return_value=mock_trace_orm)
    protocol.runtime.trace_repo.update_metrics = AsyncMock()
    
    # Bypass the step repo entirely for the high-level test
    protocol.runtime.step_runner.run_step = AsyncMock(return_value={"usage": {"total_tokens": 100}, "duration_ms": 1000})

    config = ExecutionConfigurationCreate(
        organization_id="org_1",
        protocol=ExecutionProtocol.DIRECT,
        mode=ExecutionMode.WORK,
        model_identifier="test-model"
    )

    trace = await protocol.execute("trace_123", config, {"prompt": "Test"})
    
    assert trace is not None
    assert trace.status == C10ExecutionStatus.SUCCEEDED
    protocol.runtime.trace_repo.update_metrics.assert_called_once()
    protocol.runtime.trace_repo.update_status.assert_called_once()