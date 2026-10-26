# Path: core/execution/observability/service.py
"""
Unified Observability Service Facade.
Coordinates trace recording, event dispatching, and artifact storage.
"""

from typing import Any, Dict, List, Optional, Union
from core.execution.observability.traces import TraceCollector, TraceSpan
from core.execution.observability.events import EventPublisher, C10EventType, ExecutionEvent
from core.execution.observability.artifacts import ArtifactManager, ArtifactRecord, ArtifactType


class ObservabilityService:
    """Unified engine coordinator for C10 observability operations."""

    def __init__(self, artifact_storage_dir: str = "./storage/artifacts"):
        self.publisher = EventPublisher()
        self.artifact_manager = ArtifactManager(storage_root=artifact_storage_dir)
        self._collectors: Dict[str, TraceCollector] = {}

    def get_or_create_collector(self, trace_id: str, execution_id: str) -> TraceCollector:
        """Retrieves or instantiates a trace collector for an execution."""
        if trace_id not in self._collectors:
            self._collectors[trace_id] = TraceCollector(trace_id=trace_id, execution_id=execution_id)
        return self._collectors[trace_id]

    def record_step_start(
        self,
        trace_id: str,
        execution_id: str,
        workspace_id: str,
        name: str,
        step_type: str,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> TraceSpan:
        """Starts a step span and emits a step started event."""
        collector = self.get_or_create_collector(trace_id, execution_id)
        span = collector.start_span(name=name, step_type=step_type, inputs=inputs)

        self.publisher.publish(
            event_type=C10EventType.EXECUTION_STEP_STARTED,
            workspace_id=workspace_id,
            execution_id=execution_id,
            payload={
                "span_id": span.span_id,
                "step_index": span.step_index,
                "name": name,
                "step_type": step_type,
            },
        )
        return span

    def record_step_complete(
        self,
        trace_id: str,
        span_id: str,
        workspace_id: str,
        execution_id: str,
        outputs: Optional[Dict[str, Any]] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        error_message: Optional[str] = None,
    ) -> Optional[TraceSpan]:
        """Completes a trace span and emits a step completed event."""
        collector = self._collectors.get(trace_id)
        if not collector:
            return None

        span = collector.get_span(span_id)
        if not span:
            return None

        status = "FAILED" if error_message else "COMPLETED"
        span.complete(
            status=status,
            outputs=outputs,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            error_message=error_message,
        )

        self.publisher.publish(
            event_type=C10EventType.EXECUTION_STEP_COMPLETED,
            workspace_id=workspace_id,
            execution_id=execution_id,
            payload={
                "span_id": span.span_id,
                "step_index": span.step_index,
                "status": status,
                "cost_usd": cost_usd,
                "duration_ms": span.duration_ms,
            },
        )
        return span

    def create_artifact(
        self,
        workspace_id: str,
        name: str,
        content: Union[str, bytes],
        artifact_type: ArtifactType = ArtifactType.TEXT,
        execution_id: Optional[str] = None,
        experiment_id: Optional[str] = None,
        mime_type: str = "text/plain",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArtifactRecord:
        """Stores an artifact and publishes an artifact created record."""
        record = self.artifact_manager.store_artifact(
            workspace_id=workspace_id,
            name=name,
            content=content,
            artifact_type=artifact_type,
            execution_id=execution_id,
            experiment_id=experiment_id,
            mime_type=mime_type,
            metadata=metadata,
        )
        return record

    def get_trace_summary(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves summary dict for a recorded trace."""
        collector = self._collectors.get(trace_id)
        return collector.to_summary() if collector else None