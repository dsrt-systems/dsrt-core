# Path: tests/test_c10_observability.py
"""
Unit and Integration Tests for C10 Observability Engine (Tracing, Events & Artifacts).
"""

import os
import shutil
import tempfile
import pytest
from core.execution.observability.traces import Redactor, TraceCollector
from core.execution.observability.events import EventPublisher, C10EventType
from core.execution.observability.artifacts import ArtifactManager, ArtifactType
from core.execution.observability.service import ObservabilityService


def test_redactor_string_and_dict():
    raw_text = "API Key: sk-1234567890abcdef1234567890 and Bearer secret_token_xyz_12345"
    sanitized = Redactor.redact_string(raw_text)
    assert "sk-1234567890abcdef1234567890" not in sanitized
    assert "[REDACTED]" in sanitized

    raw_data = {
        "api_key": "sk-1234567890abcdef1234567890",
        "user": "developer",
        "nested": {"password": "supersecretpassword", "safe": "hello"},
    }
    redacted = Redactor.redact_data(raw_data)
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["nested"]["password"] == "[REDACTED]"
    assert redacted["nested"]["safe"] == "hello"


def test_trace_collector_span_lifecycle():
    collector = TraceCollector(trace_id="trace_001", execution_id="exec_001")
    span = collector.start_span(name="InferenceStep", step_type="MODEL_INVOCATION", inputs={"prompt": "Hello"})
    
    assert span.step_index == 1
    assert span.status == "RUNNING"

    span.complete(
        status="COMPLETED",
        outputs={"text": "World"},
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.002,
    )

    assert span.status == "COMPLETED"
    assert span.duration_ms >= 0
    assert collector.total_cost_usd == 0.002
    assert collector.total_input_tokens == 10
    assert collector.total_output_tokens == 5


def test_event_publisher_subscriptions():
    publisher = EventPublisher()
    events_received = []

    def handler(evt):
        events_received.append(evt)

    publisher.subscribe(C10EventType.EXECUTION_STARTED.value, handler)

    publisher.publish(
        event_type=C10EventType.EXECUTION_STARTED,
        workspace_id="ws_01",
        execution_id="exec_01",
        payload={"secret": "sk-1234567890abcdef1234567890"},
    )

    assert len(events_received) == 1
    assert events_received[0].payload["secret"] == "[REDACTED]"
    assert len(publisher.get_outbox()) == 1


def test_artifact_manager_and_isolation():
    temp_dir = tempfile.mkdtemp()
    try:
        mgr = ArtifactManager(storage_root=temp_dir)
        content = "def add(a, b): return a + b"
        
        record = mgr.store_artifact(
            workspace_id="ws_tenant_A",
            name="code.py",
            content=content,
            artifact_type=ArtifactType.CODE,
            execution_id="exec_100",
        )

        assert record.size_bytes == len(content)
        assert record.sha256_hash != ""

        # Verify reading content
        retrieved_bytes = mgr.read_artifact_content(record.artifact_id, requesting_workspace_id="ws_tenant_A")
        assert retrieved_bytes.decode("utf-8") == content

        # Verify tenant security check
        with pytest.raises(PermissionError):
            mgr.get_artifact(record.artifact_id, requesting_workspace_id="ws_tenant_B")

    finally:
        shutil.rmtree(temp_dir)


def test_observability_service_integration():
    temp_dir = tempfile.mkdtemp()
    try:
        service = ObservabilityService(artifact_storage_dir=temp_dir)

        # 1. Start step
        span = service.record_step_start(
            trace_id="tr_10",
            execution_id="ex_10",
            workspace_id="ws_10",
            name="PlanExecution",
            step_type="PLANNING",
            inputs={"goal": "Write code"},
        )

        # 2. Complete step
        service.record_step_complete(
            trace_id="tr_10",
            span_id=span.span_id,
            workspace_id="ws_10",
            execution_id="ex_10",
            outputs={"plan": "Step 1, Step 2"},
            input_tokens=15,
            output_tokens=25,
            cost_usd=0.005,
        )

        # 3. Store artifact
        art_record = service.create_artifact(
            workspace_id="ws_10",
            name="plan.json",
            content='{"plan": ["Step 1", "Step 2"]}',
            artifact_type=ArtifactType.JSON,
            execution_id="ex_10",
        )

        # 4. Assert summary & event outbox
        summary = service.get_trace_summary("tr_10")
        assert summary["total_input_tokens"] == 15
        assert summary["total_cost_usd"] == 0.005

        outbox = service.publisher.get_outbox()
        assert len(outbox) == 2  # Started + Completed events
        assert art_record.artifact_id != ""

    finally:
        shutil.rmtree(temp_dir)